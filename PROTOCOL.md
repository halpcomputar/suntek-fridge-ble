# SUNTEK SC-BLE fridge protocol

Living spec. Reverse-engineered from a **BougeRV CRD2 V2.0 43QT** dual-zone 12V fridge
with a 240Wh internal battery. Update as things get confirmed.

> **This is NOT the Alpicool protocol.** Alpicool/Brass Monkey/Bodega and their rebrands
> use GATT service `1234` with binary `FE FE … sum16` frames. This device is a different
> lineage entirely — see [Alpicool comparison](#not-alpicool) at the bottom.

## Device identity

Read from the standard Device Information service (`180A`). These are **module defaults**,
not fridge-specific — any product using this BLE module will report the same strings.

| Characteristic | Value |
|---|---|
| Manufacturer Name (`2A29`) | `SUNTEK` |
| Model Number (`2A24`) | `SC-BLE-1.0` |
| Serial Number (`2A25`) | `1.0.0.0-LE` |
| Hardware Revision (`2A27`) | `1001` |
| Firmware Revision (`2A26`) | `1001` |
| Software Revision (`2A28`) | `1003` |
| PnP ID (`2A50`) | `SUNTEK\0` |
| IEEE Reg. Cert. Data (`2A2A`) | `SUNTEK IEEE Data list` |

Advertised BLE name on the reference unit: **`SYZ-D`** — the app reports this same string
as *Device Number*, so it identifies the model, not the individual unit. The app's
*Device Name* is `CRD2`.

Advertised service UUID: **`FFF0`**. DFU: no.

Advertisement manufacturer data, one sample with the unit's MAC masked:
```
XXXX XXXX XXXX 104B 0100 0000 AC00 0000 0000 0000 0000 00
└──── MAC ────┘
```
The first six bytes are the device's BLE MAC. Everything after was constant across every
observation.

Note that scanners will report a **company ID of `0x0C22`** for this field — that is an
artifact, not a real Bluetooth SIG assignment. The device writes its MAC starting at byte
0 of the manufacturer-data field, and a scanner dutifully parses the first two bytes as a
company identifier. There is no meaningful company ID here.

> ⚠️ **The MAC shown in the BougeRV app is wrong — do not match on it.** The app displays
> bytes **2–8** of the advertisement instead of 0–6, so it is shifted two bytes and picks
> up two trailing bytes that are not part of the address. On the reference unit the app
> shows `9F:C5:6A:A7:10:4B` while the actual address is `0C:22:9F:C5:6A:A7`.
>
> The real address is confirmed three ways: BlueZ/Home Assistant report it directly, it
> matches the first six advertisement bytes, and it matches the System ID characteristic
> (`2A23`) decoded per the BLE spec — reverse the little-endian value to
> `0C:22:9F:00:00:C5:6A:A7`, then strip the inserted `0000`.

**No telemetry is broadcast in the advertisement**, so passive monitoring without a
connection is not possible; a client must connect and subscribe.

## GATT

Service **`0000fff0-0000-1000-8000-00805f9b34fb`**

| Characteristic | Properties | Role |
|---|---|---|
| `FFF1` | Write, Write Without Response | Commands to the fridge |
| `FFF4` | Read, Notify (has CCCD `2902`) | Status from the fridge |

No bind/pairing handshake is required. A fresh connection can read `FFF4` immediately.

Only **one BLE connection at a time** — while a client is connected the vendor app cannot
connect, and vice versa.

## Status frame (`FFF4`)

Plain ASCII, comma-separated, newline-terminated.

```
/SC0/4/2,1,2,+54,+44,+34,+34,2,118,2,100,1,b01\n
```

**Framing:** `/SC0/` prefix, then `4/2`, then 12 comma-separated fields, then `\n` (`0x0A`).

The frame is **47 bytes**, which exceeds the default 23-byte ATT MTU. Notifications will
arrive **chunked** unless MTU is negotiated up — a client must buffer until `\n` before
parsing. Do not assume one notification == one frame.

### Fields

Values below are from the reference capture (fridge freshly loaded with room-temperature
bottled water, hence the large gap between actual and setpoint).

| # | Sample | Meaning | Status |
|---|---|---|---|
| — | `/SC0/` | Frame prefix / message type | confirmed |
| — | `4` | unknown — format version? field count? | **unknown** |
| — | `2` | unknown — zone count? device type? | **unknown** |
| 1 | `1` | Power — `1` = on | confirmed |
| 2 | `2` | Temperature unit — `1` = °C, `2` = °F | confirmed |
| 3 | `+54` | Zone 1 current temp | confirmed |
| 4 | `+44` | Zone 2 current temp | confirmed |
| 5 | `+34` | Zone 1 setpoint | confirmed |
| 6 | `+34` | Zone 2 setpoint | confirmed |
| 7 | `2` | Battery protection — `1`=L, `2`=M, `3`=H | confirmed |
| 8 | `118` | Input voltage, tenths → 11.8 V | confirmed |
| 9 | `2` | Run mode — `2` = Max, `1` = Eco | confirmed |
| 10 | `100` | unknown — hypothesis: battery percent | **unknown** |
| 11 | `1` | unknown — hypothesis: external power present | **unknown** |
| 12 | `b01` | Firmware number | confirmed |

Battery protection cut-off bands, per the app: **L** 9.6–10.9 V, **M** 10.1–11.4 V,
**H** 11.1–12.4 V.

Field 12 matches the app's *Firmware number* field exactly — it is device metadata that
happens to ride along in every status frame, not a per-frame checksum or counter.

**Zone numbering.** On the reference unit (CRD2 V2.0 43QT) **zone 1 is the larger
compartment** — the left one in the app — and zone 2 is the smaller. Verify per model
before assuming; the protocol says nothing about compartment size.

**Temperature encoding.** Always carries an explicit `+`/`-` sign, and is zero-padded to
two digits — a °C capture reads `+13,+04,+01,-01`. Parsers must not assume a fixed width
or an unsigned value.

**The unit is not cosmetic.** Switching the app to °C re-scales every temperature field in
the frame; the fridge reports in whatever unit it is displaying. A client has to read
field 2 before interpreting fields 3–6. (Confirmed by a live °F → °C capture: `+56/+41`
became `+13/+04`.)

> **Revision, 2026-07-28.** Fields 9 and 10 were initially mis-assigned (as battery
> protection and battery percent). A live capture settled it: pressing the fridge's mode
> button three times drove field 9 `2→1→2→1` — a strict two-state toggle, not a
> three-level Low/Med/High setting — and the moment it settled on `1`, input voltage rose
> `12.0 → 12.3 V` over ten seconds as the compressor throttled back. Field 9 is run mode.
> Field 7, previously assumed to be run mode, never moved and is unidentified.
>
> Field 10 is not battery percent: the reference unit has **no** optional battery pack
> installed (cutting external power shuts it off immediately) yet field 10 reads a
> constant `100`.

### Behaviour

- **Cadence:** ~4 second heartbeat, *plus* an immediate extra frame pushed on any state
  change. An integration can subscribe and never poll.
- **Constants:** fields 7, 10, 11 and 12 held steady across a ~2 minute session in which
  temperature, voltage and run mode all changed. Field 12 `b01` in particular cannot be a
  checksum or sequence number — which suggests **commands likely need no checksum either**.

### Open questions on the read side

- What is `4/2` in the header?
- **Field 10** — constant `100`. Hypothesis: battery percent. Not testable on the
  reference unit, which has no optional battery pack fitted; pulling external power
  shuts the fridge down instantly and drops the BLE link. Needs someone with the pack.
- **Field 11** — constant `1`. Two live hypotheses:
  - *Supply type, DC vs AC.* The CRD2 runs from either 12/24 V DC or 110–240 V AC, and
    the reference unit has only ever been run on DC (from an EcoFlow). **This is
    testable** — run the fridge from a wall outlet and re-read the frame.
  - *External power present.* Fits the mains-plug icon in the app header, but is not
    testable for the same reason as field 10.
- Does the frame shrink on single-zone models?

There is no panel-lock control in the app, so — unlike the Alpicool protocol — this one
likely does not expose one.

## Command surface

The complete set of writable settings, from the app's two screens. This doubles as the
capture checklist for mapping `FFF1`:

| Control | Where | Values |
|---|---|---|
| Power | main screen | on / off |
| Zone 1 setpoint | main screen ▲▼ | °F/°C value |
| Zone 2 setpoint | main screen ▲▼ | °F/°C value |
| Run mode | main screen | ECO / MAX |
| Battery protection | Device Settings | L / M / H |
| Temperature unit | Device Settings | °C / °F |

Six commands. Nothing else in the app writes to the device.

**How to close these:** change exactly one setting at a time and diff the frames.
`tools/probe.py` does this, including across reconnects — see the README for the
app-settings workflow, which matters because the fridge's own panel only exposes
power, up/down per zone, and the Eco/Max toggle. Everything else is app-only.

## Command frame (`FFF1`)

**Entirely unknown.** `FFF1` is write-only, so the format cannot be read off the device —
it has to be observed from the vendor app (`BougeRV`, `com.caption.bougerv`, by Guangzhou
Boju Information Technology).

Strong prior: since status is ASCII with a `/SCn/` prefix, commands are almost certainly
ASCII too, probably `/SC1/…` or similar.

**Capture method (iOS + macOS):**
1. Install Apple's Bluetooth logging profile on the iPhone —
   <https://developer.apple.com/download/all/?q=bluetooth>
2. Install **PacketLogger** (Additional Tools for Xcode), run it against the connected iPhone.
3. Drive the BougeRV app: change setpoint, toggle Eco/Max, power off/on, change unit.
   **Do one action at a time with a pause between**, so writes are unambiguous.
4. Filter for ATT writes to handle of `FFF1`.

On Android the equivalent is Developer options → Enable Bluetooth HCI snoop log,
then `adb pull` the btsnoop file and open in Wireshark.

> ⚠️ Don't guess-and-blast arbitrary strings at `FFF1` to find the format. The comparable
> Alpicool protocol has a factory-reset command; an unknown-protocol fuzz could plausibly
> hit something equivalent. Get the format from a capture first.

## Not Alpicool

For anyone arriving here from the Alpicool projects — quick disambiguation:

| | Alpicool lineage | This device |
|---|---|---|
| GATT service | `1234` (write `1235`, notify `1236`) | `FFF0` (write `FFF1`, notify `FFF4`) |
| Encoding | Binary | ASCII CSV |
| Framing | `FE FE \| len \| cmd \| payload \| sum16` | `/SC0/…` + `\n` |
| Bind handshake | Yes (optional on some fw) | None |
| Vendor app | `CAR FRIDGE FREEZER` (`com.alpicoolneutral.fridge.controller`) | `BougeRV` (`com.caption.bougerv`) |
| HA support | [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble), [LeanderM99/refridge](https://github.com/LeanderM99/refridge) | none — this project |

BougeRV ships **both** lineages depending on model. The CR-series is reported on the
Alpicool stack; the CRD2 V2.0 is this one. Brand and even series name are not reliable
indicators — check the GATT service.
