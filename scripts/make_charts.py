"""Draw the sector chart for the README from results/by_sector.csv."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE, INK, INK2, BLUE, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#2a78d6", "#e4e3df"

rows = list(csv.DictReader(open("results/by_sector.csv")))
rows.sort(key=lambda r: float(r["pct_negative_net_assets"]))
names = [f"{r['section_name']} ({int(r['companies']):,})" for r in rows]
vals = [float(r["pct_negative_net_assets"]) for r in rows]

fig, ax = plt.subplots(figsize=(8, 5.6), facecolor=SURFACE)
ax.set_facecolor(SURFACE)
ax.barh(names, vals, color=BLUE, height=0.62)
for y, v in enumerate(vals):
    ax.text(v + 0.6, y, f"{v:.0f}%", va="center", fontsize=9, color=INK2)
ax.set_xlim(0, max(vals) + 7)
ax.xaxis.grid(True, color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color(GRID)
ax.tick_params(colors=INK2, labelsize=9, length=0)
ax.set_xlabel("% of companies with negative net assets", color=INK2, fontsize=9)
ax.set_title("Share of small UK companies with negative net assets, by sector",
             loc="left", color=INK, fontsize=11, pad=12)
fig.text(0.01, 0.01, "Companies House accounts registered 14 to 23 Nov 2026, trading companies only (number of companies in brackets). Sign errors corrected.",
         fontsize=7.5, color=INK2)
plt.tight_layout(rect=(0, 0.03, 1, 1))
plt.savefig("results/negative_net_assets_by_sector.png", dpi=150, facecolor=SURFACE)
