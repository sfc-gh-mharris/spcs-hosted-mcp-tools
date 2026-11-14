"""Generate the architecture diagrams in this folder as SVG (Snowflake style).

    python3 docs/diagrams/build.py

Standard library only. Change a layout here and regenerate; do not hand-edit the SVGs.
The build warns when a line of text is likely wider than its box.
"""
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent

BLUE = "#29b5e8"  # Snowflake Blue: the main path
MID = "#11567f"   # Mid-Blue: Snowflake-managed things
GRAY = "#5b5b5b"
BORDER = "#e2e8f0"
GROUP = "#b6c2cf"
ICE = "#f0f9ff"
INK = "#000000"

# kind: (color, stroke width, dash, marker id)
ARROWS = {
    "ingress": (BLUE, 2, None, "a-blue"),
    "snowflake": (MID, 2, None, "a-mid"),
    "private": (GRAY, 1.5, None, "a-gray"),
    "reply": (GRAY, 1.5, "5,3", "a-gray"),
    "untested": (GRAY, 1.5, "2,3", "a-gray"),
}

LAYERS = ("container", "arrow", "node", "label")


def text_width(s, size=12, bold=False):
    return len(s) * size * (0.6 if bold else 0.53)


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2


class Diagram:
    def __init__(self, name, width, height, title, subtitle):
        self.name, self.w, self.h = name, width, height
        self.layers = {layer: [] for layer in LAYERS}
        self.text(52, 44, title, size=20, weight=700, color=INK)
        self.text(52, 66, subtitle, size=14, color=GRAY)

    # Primitives -----------------------------------------------------------------------------

    def text(self, x, y, s, size=12, weight=400, color=GRAY, anchor=None, layer="node"):
        attrs = f'x="{x:g}" y="{y:g}" fill="{color}" font-size="{size}"'
        if weight != 400:
            attrs += f' font-weight="{weight}"'
        if anchor:
            attrs += f' text-anchor="{anchor}"'
        self.layers[layer].append(f"<text {attrs}>{escape(s)}</text>")

    def rect(self, box, fill="#ffffff", stroke=BORDER, width=1.5, dash=None, rx=8, layer="node"):
        stroke_attr = f'stroke="{stroke}" stroke-width="{width}"' if stroke else 'stroke="none"'
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.layers[layer].append(
            f'<rect x="{box.x:g}" y="{box.y:g}" width="{box.w:g}" height="{box.h:g}" rx="{rx}" ry="{rx}" '
            f'fill="{fill}" {stroke_attr}{dash_attr}/>')

    def _check(self, s, size, bold, room, where):
        if text_width(s, size, bold) > room:
            print(f"  warning [{self.name}] {where}: {s!r} may overflow ({text_width(s, size, bold):.0f} > {room:.0f})")

    # Shapes ---------------------------------------------------------------------------------

    def node(self, x, y, w, title, lines=(), kind="plain", h=None, dashed=False):
        """A component box. kind: plain, accent (blue bar), ice (supporting), anchor (Snowflake-managed)."""
        h = h or 40 + 17 * len(lines)
        box = Box(x, y, w, h)
        fill, stroke, title_color, line_color = {
            "plain": ("#ffffff", BORDER, INK, GRAY),
            "accent": ("#ffffff", BORDER, INK, GRAY),
            "ice": (ICE, BORDER, INK, GRAY),
            "anchor": (MID, None, "#ffffff", "#dbeaf3"),
        }[kind]
        self.rect(box, fill=fill, stroke=stroke if not dashed else GRAY, dash="5,3" if dashed else None)
        if kind == "accent":
            self.rect(Box(x, y, 4, h), fill=BLUE, stroke=None, rx=2)
        self.text(x + 14, y + 22, title, size=14, weight=700, color=title_color)
        self._check(title, 14, True, w - 24, "title")
        for i, line in enumerate(lines):
            self.text(x + 14, y + 42 + 17 * i, line, color=line_color)
            self._check(line, 12, False, w - 24, title)
        return box

    def group(self, x, y, w, h, label, tinted=False):
        box = Box(x, y, w, h)
        if tinted:
            self.rect(box, fill=ICE, stroke=BORDER, width=1, layer="container")
            self.text(x + 12, y + 20, label, weight=700, color=MID, layer="container")
        else:
            self.rect(box, fill="none", stroke=GROUP, width=1, dash="5,3", layer="container")
            self.text(x + 12, y + 18, label, weight=700, color=GRAY, layer="container")
        self._check(label, 12, True, w - 20, "group")
        return box

    def arrow(self, points, kind="ingress", label=None, at=None):
        color, width, dash, marker = ARROWS[kind]
        path = "M " + " L ".join(f"{x:g},{y:g}" for x, y in points)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.layers["arrow"].append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}"{dash_attr} '
            f'marker-end="url(#{marker})"/>')
        if label:
            if at is None:
                (x1, y1), (x2, y2) = max(zip(points, points[1:]),
                                         key=lambda seg: abs(seg[1][0] - seg[0][0]) + abs(seg[1][1] - seg[0][1]))
                at = ((x1 + x2) / 2, (y1 + y2) / 2 + 4)
            self.label(*at, label)

    def label(self, x, y, s, anchor="middle"):
        w = text_width(s) + 10
        left = x - w / 2 if anchor == "middle" else x - 5
        self.rect(Box(left, y - 13, w, 18), fill="#ffffff", stroke=None, rx=3, layer="label")
        self.text(x, y, s, anchor=anchor if anchor == "middle" else None, layer="label")

    def note(self, x, y, lines, size=12):
        for i, line in enumerate(lines):
            self.text(x, y + 17 * i, line, size=size)

    def legend(self, x, y, items, horizontal=False, gap=24):
        for i, (kind, text) in enumerate(items):
            if horizontal:
                ix, iy = x, y
                x += 46 + text_width(text) + 28
            else:
                ix, iy = x, y + gap * i
            self.arrow([(ix, iy), (ix + 32, iy)], kind)
            self.text(ix + 42, iy + 4, text, layer="label")

    # Sequence diagrams ----------------------------------------------------------------------

    def participants(self, items, y, w, bottom):
        """items: (center x, title, subtitle, kind). Draws headers and lifelines; returns the x list."""
        for x, title, sub, kind in items:
            self.layers["container"].append(
                f'<line x1="{x:g}" y1="{y + 56:g}" x2="{x:g}" y2="{bottom:g}" stroke="{GROUP}" '
                f'stroke-width="1" stroke-dasharray="4,4"/>')
            self.node(x - w / 2, y, w, title, [sub], kind=kind, h=56)
        return [item[0] for item in items]

    def active(self, x, y1, y2):
        self.rect(Box(x - 5, y1, 10, y2 - y1), fill=ICE, stroke=MID, width=1, rx=2, layer="container")

    def message(self, y, x1, x2, label, kind="private"):
        step = 6 if x2 > x1 else -6
        self.arrow([(x1 + step, y), (x2 - step, y)], kind)
        self.label((x1 + x2) / 2, y - 8, label)

    def self_message(self, y, x, label, kind="private"):
        self.arrow([(x + 6, y), (x + 44, y), (x + 44, y + 22), (x + 7, y + 22)], kind)
        self.label(x + 54, y + 15, label, anchor="start")

    def frame(self, x, y, w, h, tag):
        self.rect(Box(x, y, w, h), fill="none", stroke=MID, width=1, rx=4, layer="container")
        tab = Box(x, y, text_width(tag, bold=True) + 16, 20)
        self.rect(tab, fill=ICE, stroke=MID, width=1, rx=4, layer="container")
        self.text(x + 8, y + 14, tag, weight=700, color=MID, layer="container")

    def side_note(self, x, y, w, s):
        self.rect(Box(x, y, w, 26), fill=ICE, stroke=BORDER, width=1, rx=4, layer="label")
        self.text(x + 10, y + 17, s, layer="label")
        self._check(s, 12, False, w - 16, "note")

    # Output ---------------------------------------------------------------------------------

    def save(self):
        head = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="{self.w}" height="{self.h}">',
            '<style>text { font-family: Arial, "Helvetica Neue", Helvetica, sans-serif; }</style>',
            "<defs>",
        ]
        for marker, color in (("a-blue", BLUE), ("a-mid", MID), ("a-gray", GRAY)):
            head.append(f'<marker id="{marker}" markerWidth="10" markerHeight="7" refX="9" refY="3.5" '
                        f'orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="{color}"/></marker>')
        head += ["</defs>", f'<rect width="{self.w}" height="{self.h}" fill="#ffffff"/>',
                 f'<rect x="40" y="24" width="4" height="28" rx="2" fill="{BLUE}"/>']
        body = [part for layer in LAYERS for part in self.layers[layer]]
        path = OUT / f"{self.name}.svg"
        path.write_text("\n".join(head + body + ["</svg>", ""]))
        print(f"wrote {path.relative_to(OUT.parent.parent)}")


# Diagrams -----------------------------------------------------------------------------------

def overview():
    d = Diagram("01-overview", 1200, 810, "Architecture overview",
                "Three SPCS services. Snowflake calls the public toolset; the server calls Cortex over SQL.")

    d.text(40, 136, "Outside Snowflake", weight=700)
    browser = d.node(40, 150, 170, "Browser", ["monitor UI", "Snowflake sign-in"])
    coco = d.node(40, 330, 170, "CoCo", ["Cortex Code", "MCP client over HTTP"])
    d.legend(40, 540, [("ingress", "Ingress, Snowflake auth"), ("snowflake", "Snowflake session token"),
                       ("private", "Private service network")])

    d.group(250, 96, 910, 690, "Snowflake account", tinted=True)

    d.group(270, 128, 220, 310, "SPCS ingress")
    ui_ing = d.node(285, 150, 190, "ui endpoint", ["public, port 8080", "<client-ingress>"])
    pub_ing = d.node(285, 330, 190, "mcp-public endpoint", ["public, port 8001", "<server-ingress>/mcp"])
    d.note(285, 258, ["Snowflake auth on each request;", "adds Sf-Context-Current-User"])

    d.group(520, 128, 390, 310, "Pool MCP_DEMO_POOL (also probe jobs)")
    client = d.node(540, 150, 350, "MCP_CLIENT (Node)", [
        "monitor UI, tool forms built from each schema",
        "every tool runs as a background job",
        "Inbound tab: what Snowflake called"], kind="accent")
    server = d.node(540, 300, 350, "MCP_SERVER (Python, mcp SDK 2.3)", [
        "port 8001 mcp-public: add",
        "port 8000 mcp, private: every tool, GET /calls",
        "CallRecorder logs calls on both ports",
        "SQL as service user, role MCP_DEMO_ROLE"], kind="accent")

    d.group(945, 128, 200, 310, "Pool MCP_COCO_POOL")
    worker = d.node(960, 300, 170, "COCO_WORKER", [
        "Agent SDK + cortex CLI", "CLI pinned, read-only", "POST /run, private"], kind="accent")

    d.group(270, 470, 870, 296, "Snowflake objects and Cortex")
    custom = d.node(285, 520, 200, "CUSTOM MCP SERVER", ["MCP_SERVER_PUBLIC", "endpoint mcp-public, /mcp"])
    agent = d.node(545, 520, 190, "Cortex Agent", ["MCP_DEMO_AGENT", "only tool: public add"])
    cortex = d.node(790, 520, 335, "Snowflake Cortex", [
        "AI_COMPLETE, AI_CLASSIFY, AI_SENTIMENT",
        "DATA_AGENT_RUN, AGENT_RUN (code_toolset_all)",
        "Cortex Code service for the CLI"], kind="anchor")
    d.node(285, 650, 450, "Roles", [
        "MCP_DEMO_ROLE owns the services, the agent, the warehouse",
        "MCP_DEMO_CONSUMER_ROLE: six grants,",
        "including the service role mcp_consumer"], kind="ice")
    d.node(790, 650, 335, "Warehouse MCP_DEMO_WH", [
        "X-Small, AUTO_SUSPEND 60 s",
        "the QUERY_WAREHOUSE of",
        "MCP_SERVER and COCO_WORKER"], kind="ice")

    d.arrow([(browser.right, 187), (ui_ing.x, 187)], "ingress", "HTTPS")
    d.arrow([(ui_ing.right, 187), (client.x, 187)], "ingress")
    d.arrow([(coco.right, 367), (pub_ing.x, 367)], "ingress", "token")
    d.arrow([(pub_ing.right, 352), (server.x, 352)], "ingress")
    d.arrow([(715, client.bottom), (715, server.y)], "private", "MCP and GET /calls")
    d.arrow([(server.right, 345), (worker.x, 345)], "private", "coco_task")
    d.arrow([(640, server.bottom), (640, agent.y)], "snowflake", "DATA_AGENT_RUN", at=(640, 458))
    d.arrow([(845, server.bottom), (845, cortex.y)], "snowflake", "AI functions, AGENT_RUN", at=(845, 458))
    d.arrow([(1045, worker.bottom), (1045, cortex.y)], "snowflake", "CLI, session token", at=(1050, 458))
    d.arrow([(agent.x, 557), (custom.right, 557)], "ingress")
    d.arrow([(385, custom.y), (385, pub_ing.bottom)], "ingress", "ingress URL", at=(385, 458))
    d.save()


def inbound():
    d = Diagram("02-snowflake-calls-us", 1200, 920, "Snowflake calls the MCP server (A1, A2)",
                "CoCo and Cortex Agents reach the public toolset through SPCS ingress.")

    coco = d.node(60, 110, 250, "CoCo (A1)", ["MCP client over HTTP", "token from a Snowflake connection"],
                  kind="accent")
    sql = d.node(360, 110, 220, "SQL user (A2)", ["SELECT DATA_AGENT_RUN(...)", "identity: that person"])
    cowork = d.node(620, 110, 220, "CoWork user (A3)", ["same agent", "not tested"], dashed=True)
    b2 = d.node(880, 110, 260, "ask_agent (B2)", ["MCP_SERVER runs the agent", "identity: MCP_SERVER"], kind="ice")

    agent = d.node(360, 250, 460, "Cortex Agent MCP_DEMO_AGENT", [
        "orchestration: auto; told to use the add tool for sums",
        "sees mcp_server_public_add, adds a description argument",
        "check warnings[] on every response"], kind="accent")
    custom = d.node(880, 250, 260, "CUSTOM MCP SERVER", [
        "MCP_SERVER_PUBLIC", "SERVICE MCP_SERVER", "ENDPOINT mcp-public, PATH /mcp"])

    band = d.node(40, 410, 1120, "SPCS ingress for endpoint mcp-public", h=96, kind="ice")
    for i, (step, detail) in enumerate([
            ("1  Authenticate", "Snowflake auth on every request"),
            ("2  Authorize", "role needs service role mcp_consumer"),
            ("3  Identify", "adds Sf-Context-Current-User"),
            ("4  Forward", "Host is the ingress hostname")]):
        x = 60 + 275 * i
        d.text(x, 460, step, size=13, weight=700, color=MID)
        d.text(x, 478, detail)
        d._check(detail, 12, False, 260, "band")
    d.note(360, 534, ["No endpoint grant: the agent still answers, skips the server, and returns warning 399540."])

    d.group(40, 560, 1120, 210, "MCP_SERVER, one process")
    host = d.node(60, 600, 250, "Host allow-list", [
        "MCP_PUBLIC_ALLOWED_HOSTS", "deploy.sh fills in the ingress host", "unknown Host: 421"], kind="accent")
    public = d.node(360, 600, 250, "Public app, port 8001", [
        "toolset: add (Factory tools next)", "no ask_agent or coco_task here,", "so an agent cannot recurse"],
        kind="accent")
    recorder = d.node(660, 600, 230, "CallRecorder", [
        "MCP middleware on both ports", "endpoint, tool, args, caller", "caller from the header"])
    private = d.node(940, 600, 200, "Private, port 8000", ["every tool", "GET /calls: the call log"], kind="ice")

    monitor = d.node(940, 810, 200, "MCP_CLIENT monitor", ["Inbound (Snowflake) tab", "polls every 2 s"],
                     kind="accent")
    d.node(60, 810, 520, "Who the tool sees as the caller", [
        "CoCo or a worksheet: the person signed in",
        "ask_agent (B2): MCP_SERVER, the service user"], kind="ice")
    d.legend(620, 822, [("ingress", "MCP over ingress"), ("snowflake", "Starts an agent run"),
                        ("private", "Inside our services"), ("untested", "Not tested")], gap=22)

    d.arrow([(470, sql.bottom), (470, agent.y)], "snowflake")
    d.arrow([(730, cowork.bottom), (730, agent.y)], "untested")
    d.arrow([(b2.cx, b2.bottom), (b2.cx, 218), (790, 218), (790, agent.y)], "snowflake")
    d.arrow([(agent.right, 295), (custom.x, 295)], "ingress")
    d.arrow([(custom.cx, custom.bottom), (custom.cx, band.y)], "ingress", "HTTPS")
    d.arrow([(coco.cx, coco.bottom), (coco.cx, band.y)], "ingress", "HTTPS, Snowflake token", at=(175, 300))
    d.arrow([(280, band.bottom), (280, host.y)], "ingress", "port 8001", at=(280, 542))
    d.arrow([(host.right, 645), (public.x, 645)], "private")
    d.arrow([(public.right, 645), (recorder.x, 645)], "private")
    d.arrow([(recorder.right, 645), (private.x, 645)], "private")
    d.arrow([(1040, private.bottom), (1040, monitor.y)], "private", "call log", at=(1040, 794))
    d.save()


def outbound():
    d = Diagram("03-we-call-cortex", 1200, 880, "MCP_SERVER calls Cortex (B1 to B4)",
                "Private tools reach Cortex with the container's session token. Nothing leaves Snowflake.")
    d.legend(760, 92, [("snowflake", "To Snowflake, session token"), ("private", "Private HTTP")],
             horizontal=True)

    caller = d.node(40, 350, 160, "MCP_CLIENT", ["or the probe job", "private network"])

    d.group(260, 110, 350, 640, "MCP_SERVER, private port 8000")
    tools = [
        d.node(280, 150, 310, "B1  AI SQL functions", [
            "cortex_complete, cortex_classify,", "cortex_sentiment", "model allow-list in the input schema"],
            kind="accent"),
        d.node(280, 290, 310, "B2  ask_agent", [
            "agent allow-list: MCP_DEMO_AGENT", "reads content[], warnings[], usage", "synchronous, up to 15 min"],
            kind="accent"),
        d.node(280, 430, 310, "B3  ask_coding_agent", [
            "inline spec, claude-sonnet-5", "permission_policy: always_allow", "read-only by instruction and grants"],
            kind="accent"),
        d.node(280, 570, 310, "B4  coco_task", [
            "httpx POST to coco-worker:8000/run", "worker runs one task at a time", "429 when it is busy"],
            kind="accent"),
    ]
    d.note(280, 692, ["snowflake.py: token re-read on every connect,", "qmark binds, QUERY_TAG spcs-mcp-demo,",
                      "warehouse from QUERY_WAREHOUSE"])

    targets = [
        d.node(680, 150, 480, "AI_COMPLETE, AI_CLASSIFY, AI_SENTIMENT", [
            "SELECT AI_COMPLETE(model => ?, prompt => ?, ...)", "about 0.0002 credits per call",
            "warehouse bills at least 60 s per resume"], kind="anchor"),
        d.node(680, 290, 480, "DATA_AGENT_RUN(agent, body)", [
            "runs MCP_DEMO_AGENT, which calls the public add (A2)", "one JSON value back, 15-minute limit",
            "about 37k tokens per run (Opus picked by auto)"], kind="anchor"),
        d.node(680, 430, 480, "AGENT_RUN(spec)", [
            "code_toolset_all sandbox: bash, files, read-only SQL, skills",
            "no agent object, nothing to host", "about 165k tokens per run"], kind="anchor"),
    ]
    worker = d.node(680, 570, 220, "COCO_WORKER", [
        "pool MCP_COCO_POOL", "Agent SDK runs the CLI", "read-only SQL callback"], kind="accent")
    cli = d.node(960, 570, 200, "Cortex Code", [
        "claude-sonnet-5, low effort", "80k to 135k tokens", "about 0.03 credits per run"], kind="anchor")

    d.node(40, 780, 1120, "Identity and usage", [
        "Every call runs as a service user (MCP_SERVER or COCO_WORKER) under MCP_DEMO_ROLE. "
        "Caller's rights is not done.",
        "Usage: CORTEX_AI_FUNCTIONS_USAGE_HISTORY (by query tag), CORTEX_AGENT_USAGE_HISTORY, "
        "CORTEX_CODE_CLI_USAGE_HISTORY. See spcs/cost.sql."], kind="ice")

    d.arrow([(caller.right, caller.cy), (260, caller.cy)], "private")
    for tool, target in zip(tools, targets):
        d.arrow([(tool.right, tool.cy), (target.x, tool.cy)], "snowflake", "SQL")
    d.arrow([(tools[3].right, tools[3].cy), (worker.x, tools[3].cy)], "private", "POST /run")
    d.arrow([(worker.right, worker.cy), (cli.x, worker.cy)], "snowflake")
    d.save()


def agent_round_trip():
    d = Diagram("04-ask-agent-round-trip", 1200, 900, "ask_agent round trip (B2 through A2)",
                "One monitor call goes out to Cortex and comes back in through the public add tool.")
    browser, client, private, agent, ingress, public = d.participants([
        (120, "Browser", "monitor UI", "plain"),
        (310, "MCP_CLIENT", "job runner", "accent"),
        (500, "MCP_SERVER", "private, port 8000", "accent"),
        (690, "Cortex Agent", "MCP_DEMO_AGENT", "anchor"),
        (880, "SPCS ingress", "mcp-public", "anchor"),
        (1070, "MCP_SERVER", "public, port 8001", "accent"),
    ], y=100, w=164, bottom=832)
    d.active(private, 290, 700)
    d.active(agent, 340, 650)
    d.active(public, 500, 600)

    d.message(200, browser, client, "POST /api/jobs", "ingress")
    d.message(240, client, browser, "202, running row", "reply")
    d.message(290, client, private, "tools/call ask_agent", "private")
    d.message(340, private, agent, "DATA_AGENT_RUN(?, ?)", "snowflake")
    d.self_message(380, agent, "plans: call add", "snowflake")
    d.message(450, agent, ingress, "mcp_server_public_add", "ingress")
    d.message(500, ingress, public, "+ Sf-Context-Current-User", "ingress")
    d.side_note(945, 530, 210, "logged: add, caller MCP_SERVER")
    d.message(600, public, agent, "result: 42", "reply")
    d.message(650, agent, private, "content[], warnings[], usage", "reply")
    d.message(700, private, client, "answer, tool calls, tokens", "reply")

    d.frame(50, 722, 360, 100, "loop every 2 s")
    d.message(770, browser, client, "GET /api/calls?sinceRev=", "ingress")
    d.message(806, client, browser, "changed rows", "reply")

    d.note(40, 862, [
        "The Inbound tab shows the nested add call with caller MCP_SERVER. "
        "The public toolset has no ask_agent, so the loop cannot recurse."])
    d.save()


def long_calls():
    d = Diagram("05-long-calls", 1200, 880, "Long tool calls: background jobs and polling",
                "No hop waits on a slow Cortex call, so no timeout along the way can cut it.")
    browser, client, server, cortex = d.participants([
        (140, "Browser", "monitor UI", "plain"),
        (460, "MCP_CLIENT", "Node, job runner", "accent"),
        (780, "MCP_SERVER", "private, port 8000", "accent"),
        (1060, "Snowflake Cortex", "or COCO_WORKER", "anchor"),
    ], y=100, w=180, bottom=730)
    d.active(client, 290, 624)
    d.active(server, 290, 560)
    d.active(cortex, 340, 510)

    d.message(200, browser, client, "POST /api/jobs {tool, args}", "ingress")
    d.message(240, client, browser, "202 at once: a running row", "reply")
    d.message(290, client, server, "tools/call, timeout 120 s or 15 min", "private")
    d.message(340, server, cortex, "one SQL call, can run minutes", "snowflake")

    d.frame(50, 372, 500, 104, "loop every 2 s while running")
    d.message(420, browser, client, "GET /api/calls?sinceRev=N", "ingress")
    d.message(458, client, browser, "only rows that changed", "reply")

    d.message(510, cortex, server, "one JSON result", "reply")
    d.message(560, server, client, "tool result", "reply")
    d.self_message(590, client, "call log: revision + 1", "private")
    d.message(660, browser, client, "GET /api/calls?sinceRev=N", "ingress")
    d.message(700, client, browser, "row done, with the result", "reply")

    d.node(40, 760, 1120, "Limits each hop stays under", [
        "Browser to MCP_CLIENT: SPCS ingress drops idle connections after 90 s, so every request returns "
        "at once and the UI polls.",
        "MCP_CLIENT to MCP_SERVER: per-tool timeouts replace the MCP SDK's 60 s default; an undici dispatcher "
        "lifts Node fetch's 300 s header limit.",
        "MCP_SERVER to Cortex: DATA_AGENT_RUN is synchronous with a 15-minute limit, which sets the agent "
        "tools' timeout."], kind="ice")
    d.save()


if __name__ == "__main__":
    for build in (overview, inbound, outbound, agent_round_trip, long_calls):
        build()
