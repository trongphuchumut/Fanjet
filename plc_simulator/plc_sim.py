"""
FanJet PLC Simulator – wxPython (Native Widgets)
Mô phỏng PLC quạt tầng hầm, giao tiếp MQTT với FanJet BMS.
Chạy: python plc_sim.py
"""

import json, random, time
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict

import wx
import wx.lib.newevent
import paho.mqtt.client as mqtt

MqttEvent, EVT_MQTT = wx.lib.newevent.NewEvent()

try:
    _V2 = hasattr(mqtt, 'CallbackAPIVersion')
except Exception:
    _V2 = False


# ── Sim Model ──

@dataclass
class SimFanUnit:
    unit_id: str
    mode: str = "auto"
    speed: int = 0
    co_ppm: float = 12.0
    tripped: bool = False
    co_warn: float = 25.0
    co_alarm: float = 50.0
    profile: list = field(default_factory=lambda: [
        {"co": 15, "speed": 30}, {"co": 25, "speed": 50},
        {"co": 35, "speed": 70}, {"co": 50, "speed": 100},
    ])

    def __post_init__(self):
        self.co_target = self.co_ppm

    def tick(self):
        if self.tripped:
            self.speed = 0
            return
        noise = random.uniform(-0.3, 0.3)
        self.co_ppm += (self.co_target - self.co_ppm) * 0.15 + noise
        self.co_ppm = max(0, round(self.co_ppm, 1))
        if self.mode == "auto":
            self.speed = self._auto_speed()

    def _auto_speed(self):
        pts = sorted(self.profile, key=lambda p: p["co"])
        co = self.co_ppm
        if not pts or co <= pts[0]["co"]:
            return 0
        if co >= pts[-1]["co"]:
            return pts[-1]["speed"]
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a["co"] <= co <= b["co"]:
                r = (co - a["co"]) / (b["co"] - a["co"])
                return int(a["speed"] + r * (b["speed"] - a["speed"]))
        return 0

    def apply_command(self, d):
        if "mode" in d:
            self.mode = d["mode"]
        if "speed" in d and self.mode == "manual":
            self.speed = max(0, min(100, int(d["speed"])))
        if d.get("reset_trip"):
            self.tripped = False

    def apply_profile(self, d):
        if "profile" in d and isinstance(d["profile"], list):
            self.profile = d["profile"]
        if "co_warn" in d:
            self.co_warn = float(d["co_warn"])
        if "co_alarm" in d:
            self.co_alarm = float(d["co_alarm"])

    def to_dict(self):
        return {"co": self.co_ppm, "speed": self.speed,
                "tripped": self.tripped, "mode": self.mode}


# ── MQTT ──

class MQTTMgr:
    def __init__(self, target):
        self._target = target
        self.client = None
        self.connected = False
        self.prefix = "fanjet/basement"
        self._log_fn = None

    def set_log(self, fn):
        self._log_fn = fn

    def connect(self, host, port, user, pwd, prefix):
        self.disconnect()
        self.prefix = prefix
        cid = f"plc-sim-{random.randint(1000,9999)}"
        try:
            if _V2:
                self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
            else:
                self.client = mqtt.Client(client_id=cid)
            if user:
                self.client.username_pw_set(user, pwd)
            self.client.on_connect = self._on_conn
            self.client.on_disconnect = self._on_disc
            self.client.on_message = self._on_msg
            self.client.connect_async(host, port, 60)
            self.client.loop_start()
        except Exception as e:
            self._log(f"[ERR] {e}")

    def disconnect(self):
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.connected = False

    def publish(self, topic, data):
        if self.client and self.connected:
            self.client.publish(topic, json.dumps(data), qos=1)

    def _on_conn(self, c, u, f, rc, *a):
        code = rc if isinstance(rc, int) else (rc.value if hasattr(rc, 'value') else int(rc))
        if code == 0:
            self.connected = True
            c.subscribe(f"{self.prefix}/+/command", 1)
            c.subscribe(f"{self.prefix}/+/profile", 1)
            self._log(f"[OK] Connected. Sub: {self.prefix}/+/command,profile")
        else:
            self._log(f"[ERR] Connect failed rc={code}")

    def _on_disc(self, *a):
        self.connected = False
        self._log("[WARN] Disconnected")

    def _on_msg(self, c, u, msg):
        try:
            parts = msg.topic.split("/")
            uid, mtype = parts[-2], parts[-1]
            payload = json.loads(msg.payload.decode())
            wx.PostEvent(self._target, MqttEvent(unit_id=uid, msg_type=mtype,
                                                  payload=payload, topic=msg.topic))
            self._log(f"[RX] {msg.topic}: {json.dumps(payload, ensure_ascii=False)[:100]}")
        except Exception as e:
            self._log(f"[ERR] {e}")

    def _log(self, t):
        if self._log_fn:
            wx.CallAfter(self._log_fn, t)


# ── Unit Panel – native widgets only ──

class UnitPanel(wx.Panel):
    def __init__(self, parent, unit: SimFanUnit):
        super().__init__(parent)
        self.unit = unit

        box = wx.StaticBox(self, label=f"  {unit.unit_id}  ")
        bsizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        # Row 1: CO, Speed, Mode, Status (4 cột)
        g1 = wx.FlexGridSizer(rows=0, cols=4, vgap=4, hgap=20)
        g1.AddGrowableCol(1)
        g1.AddGrowableCol(3)

        g1.Add(wx.StaticText(box, label="CO (ppm):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.lbl_co = wx.StaticText(box, label="0.0", size=(60, -1))
        self.lbl_co.SetFont(self.lbl_co.GetFont().Bold())
        g1.Add(self.lbl_co, 0, wx.ALIGN_CENTER_VERTICAL)

        g1.Add(wx.StaticText(box, label="Speed (%):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.lbl_speed = wx.StaticText(box, label="0", size=(40, -1))
        self.lbl_speed.SetFont(self.lbl_speed.GetFont().Bold())
        g1.Add(self.lbl_speed, 0, wx.ALIGN_CENTER_VERTICAL)

        g1.Add(wx.StaticText(box, label="Mode:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.lbl_mode = wx.StaticText(box, label="AUTO", size=(60, -1))
        self.lbl_mode.SetFont(self.lbl_mode.GetFont().Bold())
        g1.Add(self.lbl_mode, 0, wx.ALIGN_CENTER_VERTICAL)

        g1.Add(wx.StaticText(box, label="Status:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.lbl_trip = wx.StaticText(box, label="OK", size=(70, -1))
        self.lbl_trip.SetFont(self.lbl_trip.GetFont().Bold())
        self.lbl_trip.SetForegroundColour(wx.Colour(0, 128, 0))
        g1.Add(self.lbl_trip, 0, wx.ALIGN_CENTER_VERTICAL)

        g1.Add(wx.StaticText(box, label="Warn/Alarm:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.lbl_thresholds = wx.StaticText(box, label=f"{unit.co_warn:.0f} / {unit.co_alarm:.0f} ppm")
        g1.Add(self.lbl_thresholds, 0, wx.ALIGN_CENTER_VERTICAL)

        g1.Add(wx.StaticText(box, label="Profile:"), 0, wx.ALIGN_CENTER_VERTICAL)
        prof_str = ", ".join([f"{p['co']}→{p['speed']}%" for p in unit.profile])
        self.lbl_profile = wx.StaticText(box, label=prof_str)
        g1.Add(self.lbl_profile, 0, wx.ALIGN_CENTER_VERTICAL)

        bsizer.Add(g1, 0, wx.EXPAND | wx.ALL, 8)

        # Row 2: Gauge (full width)
        g2 = wx.BoxSizer(wx.HORIZONTAL)
        g2.Add(wx.StaticText(box, label="Speed:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.gauge = wx.Gauge(box, range=100, style=wx.GA_HORIZONTAL)
        g2.Add(self.gauge, 1, wx.ALIGN_CENTER_VERTICAL)
        bsizer.Add(g2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        bsizer.AddSpacer(6)

        # Row 3: CO slider + buttons
        r3 = wx.BoxSizer(wx.HORIZONTAL)
        r3.Add(wx.StaticText(box, label="CO giả lập:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.sld = wx.Slider(box, value=int(unit.co_target), minValue=0, maxValue=100,
                             style=wx.SL_HORIZONTAL | wx.SL_VALUE_LABEL)
        self.sld.Bind(wx.EVT_SLIDER, self._on_slider)
        r3.Add(self.sld, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.lbl_co_target = wx.StaticText(box, label=f"{int(unit.co_target)} ppm", size=(55, -1))
        r3.Add(self.lbl_co_target, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)

        btn_trip = wx.Button(box, label="Trip!")
        btn_trip.Bind(wx.EVT_BUTTON, self._on_trip)
        r3.Add(btn_trip, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        btn_reset = wx.Button(box, label="Reset")
        btn_reset.Bind(wx.EVT_BUTTON, self._on_reset)
        r3.Add(btn_reset, 0, wx.ALIGN_CENTER_VERTICAL)

        bsizer.Add(r3, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(bsizer)

    def _on_slider(self, e):
        self.unit.co_target = self.sld.GetValue()
        self.lbl_co_target.SetLabel(f"{self.sld.GetValue()} ppm")

    def _on_trip(self, e):
        self.unit.tripped = True
        self.unit.speed = 0

    def _on_reset(self, e):
        self.unit.tripped = False

    def refresh(self):
        u = self.unit
        self.lbl_co.SetLabel(f"{u.co_ppm:.1f}")
        self.lbl_speed.SetLabel(str(u.speed))
        self.lbl_mode.SetLabel(u.mode.upper())
        self.gauge.SetValue(min(100, max(0, u.speed)))

        # Update profile & threshold labels
        prof_str = ", ".join([f"{p['co']}→{p['speed']}%" for p in u.profile])
        self.lbl_profile.SetLabel(prof_str)
        self.lbl_thresholds.SetLabel(f"{u.co_warn:.0f} / {u.co_alarm:.0f} ppm")

        # Color CO
        if u.co_ppm >= u.co_alarm:
            self.lbl_co.SetForegroundColour(wx.RED)
        elif u.co_ppm >= u.co_warn:
            self.lbl_co.SetForegroundColour(wx.Colour(200, 120, 0))
        else:
            self.lbl_co.SetForegroundColour(wx.Colour(0, 100, 180))

        # Trip status
        if u.tripped:
            self.lbl_trip.SetLabel("TRIPPED!")
            self.lbl_trip.SetForegroundColour(wx.RED)
        else:
            self.lbl_trip.SetLabel("OK")
            self.lbl_trip.SetForegroundColour(wx.Colour(0, 128, 0))


# ── Main Frame ──

class PLCSimFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="FanJet PLC Simulator", size=(1050, 680))
        self.units: Dict[str, SimFanUnit] = {}
        self.panels: Dict[str, UnitPanel] = {}
        self.mqtt = MQTTMgr(self)
        self.mqtt.set_log(self._log)
        self.Bind(EVT_MQTT, self._on_mqtt)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._tick, self.timer)
        self._pub_cnt = 0

        panel = wx.Panel(self)
        vs = wx.BoxSizer(wx.VERTICAL)

        # ── Connection ──
        sb1 = wx.StaticBox(panel, label=" MQTT Broker ")
        s1 = wx.StaticBoxSizer(sb1, wx.HORIZONTAL)

        s1.Add(wx.StaticText(sb1, label="Host:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        self.i_host = wx.TextCtrl(sb1, value="localhost", size=(100, -1))
        s1.Add(self.i_host, 0, wx.ALL, 3)

        s1.Add(wx.StaticText(sb1, label="Port:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.i_port = wx.TextCtrl(sb1, value="1883", size=(45, -1))
        s1.Add(self.i_port, 0, wx.ALL, 3)

        s1.Add(wx.StaticText(sb1, label="User:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.i_user = wx.TextCtrl(sb1, value="", size=(60, -1))
        s1.Add(self.i_user, 0, wx.ALL, 3)

        s1.Add(wx.StaticText(sb1, label="Pass:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.i_pass = wx.TextCtrl(sb1, value="", size=(60, -1), style=wx.TE_PASSWORD)
        s1.Add(self.i_pass, 0, wx.ALL, 3)

        s1.Add(wx.StaticText(sb1, label="Prefix:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.i_pfx = wx.TextCtrl(sb1, value="fanjet/basement", size=(120, -1))
        s1.Add(self.i_pfx, 0, wx.ALL, 3)

        self.b_conn = wx.Button(sb1, label="Connect")
        self.b_conn.Bind(wx.EVT_BUTTON, self._do_connect)
        s1.Add(self.b_conn, 0, wx.ALL, 3)

        self.lbl_conn = wx.StaticText(sb1, label="  Disconnected")
        s1.Add(self.lbl_conn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)

        vs.Add(s1, 0, wx.EXPAND | wx.ALL, 5)

        # ── Sim controls ──
        sb2 = wx.StaticBox(panel, label=" Simulation ")
        s2 = wx.StaticBoxSizer(sb2, wx.HORIZONTAL)

        s2.Add(wx.StaticText(sb2, label="Unit IDs:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        self.i_units = wx.TextCtrl(sb2, value="U01,U02,U03", size=(150, -1))
        s2.Add(self.i_units, 0, wx.ALL, 3)

        s2.Add(wx.StaticText(sb2, label="Pub interval (s):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.i_int = wx.SpinCtrl(sb2, value="2", min=1, max=30, size=(50, -1))
        s2.Add(self.i_int, 0, wx.ALL, 3)

        self.b_start = wx.Button(sb2, label="Start")
        self.b_start.Bind(wx.EVT_BUTTON, self._do_start)
        s2.Add(self.b_start, 0, wx.ALL, 3)

        self.b_stop = wx.Button(sb2, label="Stop")
        self.b_stop.Bind(wx.EVT_BUTTON, self._do_stop)
        self.b_stop.Disable()
        s2.Add(self.b_stop, 0, wx.ALL, 3)

        vs.Add(s2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # ── Splitter: units | log ──
        sp = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        sp.SetMinimumPaneSize(200)

        # Left – unit cards
        self.scroll = wx.ScrolledWindow(sp)
        self.scroll.SetScrollRate(0, 10)
        self.card_sizer = wx.BoxSizer(wx.VERTICAL)
        self.scroll.SetSizer(self.card_sizer)

        # Right – log
        self.log = wx.TextCtrl(sp, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.log.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        sp.SplitVertically(self.scroll, self.log, 650)
        vs.Add(sp, 1, wx.EXPAND | wx.ALL, 5)

        panel.SetSizer(vs)
        self.CreateStatusBar()
        self.SetStatusText("Ready")
        self.Centre()

        # Auto-start
        wx.CallAfter(self._do_start, None)

    def _do_connect(self, e):
        self.mqtt.connect(
            self.i_host.GetValue().strip() or "localhost",
            int(self.i_port.GetValue() or 1883),
            self.i_user.GetValue().strip(),
            self.i_pass.GetValue().strip(),
            self.i_pfx.GetValue().strip() or "fanjet/basement",
        )

    def _do_start(self, e):
        ids = [x.strip() for x in self.i_units.GetValue().split(",") if x.strip()]
        if not ids:
            return
        self.card_sizer.Clear(True)
        self.units.clear()
        self.panels.clear()
        for uid in ids:
            unit = SimFanUnit(uid)
            self.units[uid] = unit
            p = UnitPanel(self.scroll, unit)
            self.panels[uid] = p
            self.card_sizer.Add(p, 0, wx.EXPAND | wx.BOTTOM, 4)
        self.scroll.FitInside()
        self.scroll.Layout()
        self._pub_cnt = 0
        self.timer.Start(1000)
        self.b_start.Disable()
        self.b_stop.Enable()
        self._log(f"[SIM] Started: {', '.join(ids)}")

    def _do_stop(self, e):
        self.timer.Stop()
        self.b_start.Enable()
        self.b_stop.Disable()
        self._log("[SIM] Stopped")

    def _tick(self, e):
        self._pub_cnt += 1
        for u in self.units.values():
            u.tick()
        for p in self.panels.values():
            p.refresh()
        if self._pub_cnt >= self.i_int.GetValue() and self.mqtt.connected:
            self._pub_cnt = 0
            pfx = self.i_pfx.GetValue().strip() or "fanjet/basement"
            for uid, u in self.units.items():
                self.mqtt.publish(f"{pfx}/{uid}/telemetry", u.to_dict())
            self._log(f"[TX] Telemetry x{len(self.units)}")
        # Status bar
        st = "Connected" if self.mqtt.connected else "Disconnected"
        self.lbl_conn.SetLabel(f"  {st}")
        self.lbl_conn.SetForegroundColour(
            wx.Colour(0, 128, 0) if self.mqtt.connected else wx.RED)
        self.SetStatusText(f"{st} | {len(self.units)} units | tick")

    def _on_mqtt(self, evt):
        uid = evt.unit_id
        if uid in self.units:
            if evt.msg_type == "command":
                self.units[uid].apply_command(evt.payload)
                self._log(f"[CMD] {uid}: {evt.payload}")
            elif evt.msg_type == "profile":
                self.units[uid].apply_profile(evt.payload)
                self._log(f"[PROFILE] {uid} updated: {evt.payload}")
            # Refresh UI immediately after applying changes
            if uid in self.panels:
                self.panels[uid].refresh()
        else:
            self._log(f"[WARN] Unknown unit '{uid}' (msg_type={evt.msg_type}). Known: {list(self.units.keys())}")

    def _log(self, t):
        ts = time.strftime("%H:%M:%S")
        self.log.AppendText(f"[{ts}] {t}\n")


if __name__ == "__main__":
    app = wx.App()
    PLCSimFrame().Show()
    app.MainLoop()
