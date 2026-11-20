"""One-off script to render docs/architecture.png. Not part of the app --
run manually if the diagram ever needs regenerating."""

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D

fig, ax = plt.subplots(figsize=(11, 8.5))
ax.set_xlim(0, 110)
ax.set_ylim(0, 100)
ax.axis("off")

NAVY = "#1a2744"
BLUE = "#2c5282"
GREEN = "#2f6b4f"
AMBER = "#8a5a1e"
GREY = "#555555"
LINE = "#333333"


def box(x, y, w, h, text, sub=None, color=NAVY, fontsize=10.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.35,rounding_size=3",
                                 linewidth=1.4, edgecolor=color, facecolor="white"))
    if sub:
        ax.text(x + w / 2, y + h * 0.62, text, ha="center", va="center",
                fontsize=fontsize, fontweight="bold", color=color)
        ax.text(x + w / 2, y + h * 0.28, sub, ha="center", va="center",
                fontsize=8.3, color=GREY)
    else:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fontsize, fontweight="bold", color=color)


def arrow(x1, y1, x2, y2, color=LINE, style="-|>", lw=1.3, connectionstyle=None):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=13,
                                  linewidth=lw, color=color,
                                  connectionstyle=connectionstyle))


# Title
ax.text(55, 97, "ElevateBox Voice AI Agent -- Architecture", ha="center", fontsize=15, fontweight="bold", color=NAVY)
ax.text(55, 93.5, "Caller \u2192 OmniDimension (telephony + STT/LLM/TTS) \u2192 FastAPI decision engine \u2192 WhatsApp / Scheduler / Persistence",
        ha="center", fontsize=9, color=GREY)

# Row 1: Caller + Telephony/voice platform
box(4, 80, 20, 10, "Evaluator", "phone call (Telugu / Hindi / English)", color=GREY)
box(30, 80, 34, 10, "OmniDimension", "outbound dispatch \u2022 STT \u2022 conversational LLM \u2022 TTS\nbarge-in / interruption handling", color=BLUE)
box(70, 80, 34, 10, "Meta WhatsApp\nCloud API", "mid-call + follow-up delivery", color=GREEN)

arrow(24, 85, 30, 85)
arrow(64, 85, 70, 88)  # OmniDimension can also call WhatsApp natively; primary path is via our backend below

# Row 2: Custom API / webhook bridge into our backend
box(30, 62, 34, 10, "Custom API actions\n(tool calls, mid-call)", "update_lead_signals \u2022 schedule_callback\ntrigger_midcall_whatsapp", color=BLUE, fontsize=9.5)
arrow(47, 80, 47, 72)

# Row 3: FastAPI backend core
box(14, 44, 66, 12, "FastAPI backend  (this repository)", "webhooks \u2192 extraction validation \u2192 cumulative signal merge \u2192\nDETERMINISTIC decision engine \u2192 idempotency-guarded actions", color=NAVY, fontsize=11)
arrow(47, 62, 47, 56)

# Row 4: three outputs
box(6, 26, 26, 10, "WhatsApp client", "Meta Cloud API\n(mock when no token)", color=GREEN, fontsize=9.5)
box(37, 26, 26, 10, "Callback scheduler", "deterministic EN/HI/TE\ntime parser \u2192 Asia/Kolkata", color=AMBER, fontsize=9.5)
box(68, 26, 26, 10, "Claude (Anthropic API)", "extraction fallback +\nfollow-up polish (optional)", color=BLUE, fontsize=9.5)

arrow(30, 44, 19, 36)
arrow(47, 44, 50, 36)
arrow(64, 44, 81, 36)

# Row 5: persistence
box(20, 8, 60, 10, "PostgreSQL (SQLite for local dev)  --  SQLAlchemy async",
    "Call \u2022 Lead (LeadState JSONB) \u2022 ConversationTurn \u2022 ScheduledCallback \u2022 OutboundAction", color=GREY, fontsize=10)
arrow(19, 26, 35, 18)
arrow(50, 26, 50, 18)
arrow(81, 26, 65, 18)

# Legend: real vs mock
ax.text(4, 3, "Solid boxes = fully implemented & locally tested.  WhatsApp / OmniDimension / Claude calls run against", fontsize=7.6, color=GREY)
ax.text(4, 1, "mock adapters in this environment (no external network/credentials available) -- see README for what's verified vs. blocked.", fontsize=7.6, color=GREY)

plt.tight_layout()
plt.savefig("/home/claude/elevatebox-voice-agent/docs/architecture.png", dpi=200, bbox_inches="tight", facecolor="white")
print("saved")
