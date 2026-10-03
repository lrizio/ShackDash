<?php
/*
 * m5status.php v1.5 — JSON status endpoint for M5Stack CoreS3 D-STAR/YSF/DMR monitor
 *
 * v1.5: DMR lastheard entries were showing the numeric radio ID
 *       (e.g. "5053139") instead of a callsign -- that's genuinely
 *       what MMDVMHost logs for DMR (unlike D-STAR/YSF, which log
 *       callsigns directly), so this resolves it against WPSD's own
 *       /usr/local/etc/DMRIds.dat radioid.net snapshot, the same
 *       database the web dashboard already uses. IDs not (yet) in
 *       that database -- unregistered, or a talkgroup/system ID --
 *       still show as the raw number, same as before.
 *
 * v1.4: confirmed DMR lastheard parsing against real live traffic
 *       (192.168.4.56's DMR master got reconfigured and connected) --
 *       the v1.3 format guess was correct, no changes needed there.
 *       Added positive DMR link detection now that a real "connection
 *       succeeded" message exists to key off: "DMR+_NETWORK, Logged
 *       into the master successfully". Whichever of the last login or
 *       last timeout is more recent wins. This also fixed a real v1.3
 *       bug: a box that failed, then got reconfigured and reconnected
 *       to a *different* network kept showing 'unlinked', because the
 *       old timeout was still within the 10-minute recency window and
 *       nothing accounted for a later success overriding it.
 *
 * v1.3: added DMR lastheard + connection-failure detection, for
 *       hotspots running DMRGateway. Written without a live confirmed
 *       sample (see v1.4 above for how that was resolved) -- DMR Slot
 *       header/end-of-voice-transmission parsing is based on
 *       MMDVMHost's standard documented log format (mirrors D-STAR's
 *       header/end pattern: "DMR Slot N, received RF|network voice
 *       header from CALL to TG N" / "... end of voice transmission
 *       from CALL, N seconds, ...").
 *
 * v1.2: added YSF (System Fusion) support, for hotspots running
 *       YSFGateway instead of ircDDBGateway (confirmed on Americalink,
 *       which turned out to be YSF, not D-STAR as its name suggested).
 *       YSFGateway's own log doesn't record explicit link/unlink events
 *       the way ircDDBGateway does, so YSF link state + lastheard are
 *       both derived from the MMDVM log's "YSF, received network data
 *       from CALL to DG-ID N at REFLECTOR" / "YSF, network watchdog has
 *       expired, N seconds" line pairs -- same style as D-STAR's
 *       existing MMDVM-header fallback, just used as the primary source
 *       since there's no gateway-log equivalent to prefer over it.
 *
 * v1.1: link-state parsing matched to actual WPSD ircDDBGateway log lines
 *       ("D-Plus link to REF023 C established", "... has failed",
 *        "Removing outgoing ... link", "has unlinked"), greps the whole
 *       gateway log (today + yesterday) instead of a tail window, and
 *       falls back to the most recent "via REFxxx X" in the MMDVM log.
 *
 * Install:
 *   scp to /home/pi-star/dstar-web/m5status.php
 *   sudo cp /home/pi-star/dstar-web/m5status.php /var/www/dashboard/
 *   sudo chown www-data:www-data /var/www/dashboard/m5status.php
 *
 * Debug: http://192.168.4.23/m5status.php?debug=1
 */

header('Content-Type: application/json');
header('Cache-Control: no-cache');

$LOGDIR     = '/var/log/pi-star';
$TAIL_LINES = 600;   // how far back to look in today's MMDVM log
$MAX_HEARD  = 6;     // max last-heard entries to return

$debug = isset($_GET['debug']);
$dbg   = array();

/* ---------- helpers ---------- */

function tail_file($path, $lines) {
    if (!is_readable($path)) return array();
    $out = shell_exec('tail -n ' . intval($lines) . ' ' . escapeshellarg($path));
    if ($out === null) return array();
    return explode("\n", $out);
}

function newest_log($dir, $prefix) {
    $files = glob($dir . '/' . $prefix . '-*.log');
    if (!$files) return null;
    usort($files, function ($a, $b) { return strcmp($b, $a); }); // name sort = date sort
    return $files[0];
}

/* MMDVMHost + ircDDBGateway log timestamps are UTC */
function log_ts_to_epoch($ts) {
    return strtotime($ts . ' UTC');
}

function norm_target($t) {
    return preg_replace('/\s+/', ' ', trim($t));
}

/* ---------- system info ---------- */

$resp = array();
$resp['time']     = time();
$resp['hostname'] = trim(@file_get_contents('/etc/hostname'));

$t = @file_get_contents('/sys/class/thermal/thermal_zone0/temp');
$resp['cpu_temp'] = ($t !== false) ? round(intval($t) / 1000.0, 1) : null;

$u = @file_get_contents('/proc/uptime');
$resp['uptime'] = ($u !== false) ? intval(floatval(explode(' ', $u)[0])) : null;

$load = sys_getloadavg();
$resp['load'] = round($load[0], 2);

$resp['mmdvm_running'] = (trim(shell_exec('pgrep -x MMDVMHost')) !== '');

/* ---------- D-STAR link state (ircDDBGateway log, full-file grep) ---------- */

$link = array('state' => 'unknown', 'target' => '', 'since' => null);

$gwfiles = glob($LOGDIR . '/ircDDBGateway-*.log');
if (!$gwfiles) $gwfiles = glob($LOGDIR . '/ircddbgateway-*.log');

if ($gwfiles) {
    sort($gwfiles);                          // oldest -> newest (date in name)
    $gwfiles = array_slice($gwfiles, -2);    // yesterday + today covers any uptime span

    $cmd = 'grep -hE '
         . escapeshellarg('link to .* established|link to .* has failed|Removing outgoing|has unlinked')
         . ' ' . implode(' ', array_map('escapeshellarg', $gwfiles)) . ' 2>/dev/null';
    $glines = explode("\n", (string)shell_exec($cmd));

    foreach ($glines as $line) {
        $when = null;
        if (preg_match('/^[A-Z]: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/', $line, $tm)) {
            $when = log_ts_to_epoch($tm[1]);
        }

        // "D-Plus link to REF023 C established" / "DCS link to DCS006 C established"
        // / "DExtra link to XRF999 A established"
        if (preg_match('/link to ((?:REF|XRF|DCS|XLX)\d+\s+[A-Z]) established/i', $line, $m)) {
            $link = array('state' => 'linked', 'target' => norm_target($m[1]), 'since' => $when);
            if ($debug) $dbg['link_line'] = trim($line);
        }
        // "link to REF023 C has failed" — but NOT "has failed to connect",
        // which refers to a pending link that never came up
        elseif (preg_match('/link to ((?:REF|XRF|DCS|XLX)\d+\s+[A-Z]) has failed(?! to connect)/i', $line, $m)) {
            if ($link['state'] === 'linked' && norm_target($m[1]) === $link['target']) {
                $link = array('state' => 'unlinked', 'target' => '', 'since' => $when);
                if ($debug) $dbg['link_line'] = trim($line);
            }
        }
        // "Removing outgoing D-Plus link VK3EI  B, REF023 C"
        elseif (preg_match('/Removing outgoing .*link .*?,\s*((?:REF|XRF|DCS|XLX)\d+\s+[A-Z])/i', $line, $m)) {
            if ($link['state'] === 'linked' && norm_target($m[1]) === $link['target']) {
                $link = array('state' => 'unlinked', 'target' => '', 'since' => $when);
                if ($debug) $dbg['link_line'] = trim($line);
            }
        }
        // "Remote control user has unlinked ..."
        elseif (preg_match('/has unlinked/i', $line)) {
            $link = array('state' => 'unlinked', 'target' => '', 'since' => $when);
            if ($debug) $dbg['link_line'] = trim($line);
        }
    }
    if ($debug) $dbg['gw_files'] = $gwfiles;
} else {
    if ($debug) $dbg['gw_files'] = 'NOT FOUND';
}

/* ---------- last heard (MMDVM log) ---------- */

$heard = array();   // list, newest last
$open  = array();   // call (or '__ysf__' sentinel) => index into $heard, awaiting end-of-tx
$lastVia = '';      // most recent D-STAR "via REFxxx X" seen (fallback link source)
$lastViaTime = null;
$ysfVia = '';       // most recent YSF "at REFLECTOR" seen (link source -- there's no
$ysfViaTime = null; // gateway-log equivalent to prefer over this, so it's not just a fallback)

$mmlog = newest_log($LOGDIR, 'MMDVM');
if ($mmlog !== null) {
    $lines = tail_file($mmlog, $TAIL_LINES);
    foreach ($lines as $line) {
        $isDstar = strpos($line, 'D-Star') !== false;
        $isYsf   = strpos($line, 'YSF') !== false;
        $isDmr   = strpos($line, 'DMR Slot') !== false;
        if (!$isDstar && !$isYsf && !$isDmr) continue;

        if (!preg_match('/^[A-Z]: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/', $line, $tm)) continue;
        $when = log_ts_to_epoch($tm[1]);

        if ($isDstar) {
        // Header: "received RF header from VK3EI   /LINO to CQCQCQ"
        //         "received network header from VK3TEH  /9700 to CQCQCQ   via REF023 C"
        if (preg_match('/received (RF|network) header from (\S+)\s*\/(\S*)\s+to\s+(\S+(?:\s+[A-Z])?)(?:\s+via\s+(\S+(?:\s+[A-Z])?))?/', $line, $m)) {
            $call = trim($m[2]);
            $entry = array(
                'call' => $call,
                'sfx'  => trim($m[3]),
                'src'  => ($m[1] === 'RF') ? 'RF' : 'NET',
                'to'   => trim($m[4]),
                'time' => $when,
                'dur'  => null,
                'ber'  => null,
                'loss' => null,
            );
            $heard[] = $entry;
            $open[$call] = count($heard) - 1;
            if (isset($m[5]) && $m[5] !== '') {
                $lastVia = norm_target($m[5]);
                $lastViaTime = $when;
            }
            if ($debug) $dbg['hdr'][] = trim($line);
        }

        // End: "... end of transmission from VK3EI   /LINO to CQCQCQ  , 2.7 seconds, BER: 0.0%, RSSI: ..."
        //      network variant adds "x% packet loss,"
        elseif (preg_match('/received (?:RF|network) end of transmission from (\S+).*?([\d.]+) seconds(?:, (\d+)% packet loss)?(?:, BER: ([\d.]+)%)?/', $line, $m)) {
            $call = trim($m[1]);
            if (isset($open[$call])) {
                $i = $open[$call];
                $heard[$i]['dur']  = floatval($m[2]);
                if (isset($m[3]) && $m[3] !== '') $heard[$i]['loss'] = intval($m[3]);
                if (isset($m[4]) && $m[4] !== '') $heard[$i]['ber']  = floatval($m[4]);
                unset($open[$call]);
            }
            if ($debug) $dbg['end'][] = trim($line);
        }

        // Watchdog / lost: "... transmission lost from VK3EI ..."
        elseif (preg_match('/transmission lost from (\S+)/', $line, $m)) {
            unset($open[trim($m[1])]);
        }
        } // $isDstar

        elseif ($isYsf) {
        // "YSF, received network data from KE8ZKN     to DG-ID 0 at FCS002-90"
        // Unlike D-STAR there's no separate header/end-of-tx pair -- one
        // data line opens/refreshes the current burst, and the next
        // watchdog-expired line (below) closes it with a duration. The
        // callsign field sometimes carries a YSF-specific /SUFFIX or
        // -SUFFIX (not the same convention as D-STAR's module letter),
        // so it's kept as part of 'call' rather than split into 'sfx'.
        if (preg_match('/received network data from (\S+)\s+to DG-ID (\d+) at (\S+)/', $line, $m)) {
            $call = trim($m[1]);
            $entry = array(
                'call' => $call,
                'sfx'  => '',
                'src'  => 'NET',
                'to'   => 'DG-ID ' . $m[2],
                'time' => $when,
                'dur'  => null,
                'ber'  => null,
                'loss' => null,
            );
            $heard[] = $entry;
            $open['__ysf__'] = count($heard) - 1;
            $ysfVia = norm_target($m[3]);
            $ysfViaTime = $when;
            if ($debug) $dbg['ysf_hdr'][] = trim($line);
        }

        // "YSF, network watchdog has expired, 0.5 seconds, 0% packet loss, BER: 0.0%"
        elseif (preg_match('/network watchdog has expired, ([\d.]+) seconds(?:, (\d+)% packet loss)?(?:, BER: ([\d.]+)%)?/', $line, $m)) {
            if (isset($open['__ysf__'])) {
                $i = $open['__ysf__'];
                $heard[$i]['dur']  = floatval($m[1]);
                if (isset($m[2]) && $m[2] !== '') $heard[$i]['loss'] = intval($m[2]);
                if (isset($m[3]) && $m[3] !== '') $heard[$i]['ber']  = floatval($m[3]);
                unset($open['__ysf__']);
            }
            if ($debug) $dbg['ysf_end'][] = trim($line);
        }
        } // $isYsf

        elseif ($isDmr) {
        // UNVERIFIED against live traffic -- see the v1.3 header comment.
        // "DMR Slot 1, received RF voice header from N0CALL to TG 91"
        // "DMR Slot 1, received network voice header from N0CALL to TG 91"
        if (preg_match('/DMR Slot (\d+), received (RF|network) voice header from (\S+) to (TG\s+\d+|\S+)/', $line, $m)) {
            $call = trim($m[3]);
            $entry = array(
                'call' => $call,
                'sfx'  => '',
                'src'  => ($m[2] === 'RF') ? 'RF' : 'NET',
                'to'   => 'TS' . $m[1] . ' ' . norm_target($m[4]),
                'time' => $when,
                'dur'  => null,
                'ber'  => null,
                'loss' => null,
            );
            $heard[] = $entry;
            $open[$call] = count($heard) - 1;
            if ($debug) $dbg['dmr_hdr'][] = trim($line);
        }

        // "DMR Slot 1, received RF end of voice transmission from N0CALL, 4.5 seconds, BER: 0.0%, RSSI: ..."
        //  network variant adds "x% packet loss,"
        elseif (preg_match('/DMR Slot \d+, received (?:RF|network) end of voice transmission from (\S+).*?([\d.]+) seconds(?:, (\d+)% packet loss)?(?:, BER: ([\d.]+)%)?/', $line, $m)) {
            $call = trim($m[1]);
            if (isset($open[$call])) {
                $i = $open[$call];
                $heard[$i]['dur']  = floatval($m[2]);
                if (isset($m[3]) && $m[3] !== '') $heard[$i]['loss'] = intval($m[3]);
                if (isset($m[4]) && $m[4] !== '') $heard[$i]['ber']  = floatval($m[4]);
                unset($open[$call]);
            }
            if ($debug) $dbg['dmr_end'][] = trim($line);
        }
        } // $isDmr
    }
    if ($debug) $dbg['mmdvm_log'] = $mmlog;
} else {
    if ($debug) $dbg['mmdvm_log'] = 'NOT FOUND';
}

/* DMR shows numeric radio IDs in its log, not callsigns (unlike
 * D-STAR/YSF) -- resolve them against WPSD's own DMR ID database (the
 * same radioid.net snapshot the web dashboard already uses), synced
 * periodically to /usr/local/etc/DMRIds.dat as "ID<TAB>CALLSIGN<TAB>
 * NAME". Only greps for the specific IDs actually seen this request,
 * not the whole 300k+-line file into PHP memory -- cheap even on a
 * Pi 3B+. An ID with no match (not yet synced from the registry, or a
 * talkgroup/system ID rather than a personal one) is left showing as
 * the raw number, same as before this lookup existed -- not an error. */
$DMRIDDB = '/usr/local/etc/DMRIds.dat';
if (is_readable($DMRIDDB)) {
    $ids = array();
    foreach ($heard as $h) {
        if (ctype_digit($h['call'])) $ids[$h['call']] = true;
    }
    if ($ids) {
        $pattern = implode('|', array_map('preg_quote', array_keys($ids)));
        $cmd = 'grep -E ' . escapeshellarg('^(' . $pattern . ')\t') . ' ' . escapeshellarg($DMRIDDB) . ' 2>/dev/null';
        $rows = explode("\n", (string)shell_exec($cmd));
        $idToCall = array();
        foreach ($rows as $row) {
            $f = explode("\t", $row);
            if (count($f) >= 2 && $f[1] !== '') $idToCall[$f[0]] = trim($f[1]);
        }
        foreach ($heard as &$h) {
            if (isset($idToCall[$h['call']])) {
                $h['sfx']  = $h['call'];   // keep the raw ID visible as sfx, same slot D-STAR uses for its module suffix
                $h['call'] = $idToCall[$h['call']];
            }
        }
        unset($h);
        if ($debug) $dbg['dmr_id_lookups'] = $idToCall;
    }
}

/* Fallback / primary-for-YSF link source, in priority order:
 * 1. D-STAR gateway log (already set above if found)
 * 2. D-STAR MMDVM-header "via REFxxx X" fallback
 * 3. YSF MMDVM-data "at REFLECTOR" (no gateway-log equivalent exists) */
if ($link['state'] === 'unknown' && $lastVia !== '') {
    $link = array('state' => 'linked', 'target' => $lastVia, 'since' => $lastViaTime);
    if ($debug) $dbg['link_line'] = 'fallback: via ' . $lastVia . ' from MMDVM headers';
} elseif ($link['state'] === 'unknown' && $ysfVia !== '') {
    $link = array('state' => 'linked', 'target' => $ysfVia, 'since' => $ysfViaTime);
    if ($debug) $dbg['link_line'] = 'YSF: at ' . $ysfVia . ' from MMDVM data lines';
}

/* DMR: only checked if nothing above already found a real link, so this
 * can't override a genuine D-STAR/YSF result on a multi-mode hotspot.
 *
 * v1.3 shipped with only the failure case trusted, since no live
 * connection existed yet to confirm the success message -- that's now
 * confirmed against a real reconnect: "DMR+_IPSC2-ANDALUCIA, Logged
 * into the master successfully". Both the last login and the last
 * timeout are found, and whichever is more recent wins -- v1.3's bug
 * was trusting a stale timeout even after a *later* successful login
 * on a different network (a box that failed, then got reconfigured and
 * reconnected, kept showing 'unlinked' because the old timeout was
 * still within the 10-minute recency window). A stuck retry loop still
 * can't fake a login line, so this remains safe against that case. */
$dmrfiles = glob($LOGDIR . '/DMRGateway-*.log');
if ($dmrfiles) {
    sort($dmrfiles);
    $dmrfiles = array_slice($dmrfiles, -2);
    $filesArg = implode(' ', array_map('escapeshellarg', $dmrfiles));

    $cmd = 'grep -hE ' . escapeshellarg('Connection to the master has timed out')
         . ' ' . $filesArg . ' 2>/dev/null | tail -1';
    $lastTimeout = trim((string)shell_exec($cmd));
    $timeoutWhen = null;
    if ($lastTimeout !== '' && preg_match('/^[A-Z]: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/', $lastTimeout, $tm)) {
        $timeoutWhen = log_ts_to_epoch($tm[1]);
    }

    $cmd = 'grep -hE ' . escapeshellarg('Logged into the master successfully')
         . ' ' . $filesArg . ' 2>/dev/null | tail -1';
    $lastLogin = trim((string)shell_exec($cmd));
    $loginWhen = null;
    $loginNet  = '';
    if ($lastLogin !== '' && preg_match('/^[A-Z]: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.\d+)? (\S+), Logged/', $lastLogin, $lm)) {
        $loginWhen = log_ts_to_epoch($lm[1]);
        $loginNet  = norm_target(preg_replace('/^DMR\+?_?/i', '', $lm[2]));   // "IPSC2-ANDALUCIA" -> "ANDALUCIA"-ish, keep whatever's left
    }

    if ($link['state'] === 'unknown' && $loginWhen !== null && ($timeoutWhen === null || $loginWhen > $timeoutWhen)) {
        $link = array('state' => 'linked', 'target' => $loginNet, 'since' => $loginWhen);
        if ($debug) $dbg['link_line'] = trim($lastLogin) . ' (DMR: login is more recent than any timeout)';
    } elseif ($link['state'] === 'unknown' && $timeoutWhen !== null && (time() - $timeoutWhen) < 600) {
        $link = array('state' => 'unlinked', 'target' => '', 'since' => $timeoutWhen);
        if ($debug) $dbg['link_line'] = trim($lastTimeout) . ' (DMR: timeout is more recent than any login, and recent)';
    }
    if ($debug) $dbg['dmr_gw_files'] = $dmrfiles;
} else {
    if ($debug) $dbg['dmr_gw_files'] = 'NOT FOUND';
}

$resp['link'] = $link;

/* De-duplicate by callsign, keep most recent, newest first */
$byCall = array();
foreach ($heard as $h) $byCall[$h['call']] = $h;     // later entries overwrite
$list = array_values($byCall);
usort($list, function ($a, $b) { return $b['time'] - $a['time']; });
$resp['lastheard'] = array_slice($list, 0, $MAX_HEARD);

/* Currently transmitting? (header seen with no end yet, within last 90 s).
 * Reads the call from $heard[$i], not the $open key -- YSF entries are
 * keyed by the '__ysf__' sentinel there, not a real callsign. */
$resp['tx_active'] = null;
foreach ($open as $i) {
    if ($resp['time'] - $heard[$i]['time'] < 90) {
        $resp['tx_active'] = array('call' => $heard[$i]['call'], 'src' => $heard[$i]['src']);
    }
}

if ($debug) $resp['debug'] = $dbg;

echo json_encode($resp);
