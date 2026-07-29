# SUNTEK SC-BLE fridge → Home Assistant

Reverse-engineering a **BougeRV CRD2 V2.0** dual-zone 12V fridge (43QT, 240Wh battery)
so Home Assistant can read and eventually control it locally over BLE.

The fridge uses a generic **SUNTEK `SC-BLE-1.0`** module speaking plain ASCII over GATT
service `FFF0` — *not* the Alpicool `1234` binary protocol that the existing community
fridge integrations implement. Nothing published covers this one, so: new project.

Because the module is generic, this likely applies to a range of rebadged 12V fridges,
not just BougeRV. If the device advertises `FFF0` and the manufacturer string reads
`SUNTEK`, it's probably this protocol.

**[PROTOCOL.md](PROTOCOL.md) is the real artifact here** — the spec, what's confirmed,
and what's still unknown.

## Status

- ✅ GATT layout mapped — `FFF1` write, `FFF4` read/notify, no bind handshake
- ✅ Status frame decoded — 10 of 12 fields confirmed against the fridge's own display
- ⬜ Remaining read-side unknowns (header digits, fields 11–12, Eco/°C values)
- ⬜ Command format — needs a capture of the vendor app writing to `FFF1`
- ⬜ Home Assistant integration

## Layout

```
PROTOCOL.md          the spec — confirmed fields, open questions, capture method
tools/probe.py       live BLE probe: subscribe, decode, diff frames
captures/            raw frame logs (written by probe.py)
```

## Running the probe

The fridge accepts **one BLE connection at a time** — force-quit the BougeRV app first,
or the probe won't be able to connect.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 tools/probe.py
```

On macOS the terminal app needs Bluetooth permission
(System Settings → Privacy & Security → Bluetooth) the first time.

The probe prints each status frame decoded, highlighting fields that changed since the
last one. To map an unknown field: start the probe, then change **exactly one** setting
on the fridge's physical panel and watch which line lights up.

### Mapping app-only settings

The fridge's own panel only exposes power, up/down per zone, and the Eco/Max toggle —
everything else lives in the app. Since only one BLE client can connect at a time, you
can't watch live while using the app. Instead the probe **persists its last frame and
diffs across sessions**:

```bash
python3 tools/probe.py --once     # snapshot current state, then quit
```

Then: open the app, change **one** setting, force-quit the app, and run `--once` again.
The changed field is highlighted against the previous session's baseline.

## Credit

Protocol disambiguation and the Alpicool comparison draw on
[Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble),
[LeanderM99/refridge](https://github.com/LeanderM99/refridge), and
[dandwhelan/Alpicool50l12vfridgefreezer](https://github.com/dandwhelan/Alpicool50l12vfridgefreezer) —
different protocol, but their work is what made it fast to rule out.
