PROJECT BRIEF — Demand Monitor (3D Printing)
Owner Goal
Build a practical demand intelligence system for 3D-printed products first, then later for local 3D printing services. The system should help identify real demand, measure opportunity, and make clear what to act on.
Current Business Strategy

Phase 1 (now): Design and sell my own products (mounts, accessories, functional parts) to learn the craft, dial in the Bambu Lab P1S, generate cash flow, and understand real customer feedback.
Phase 2 (later): Offer manufacturing / printing services to small businesses and entrepreneurs (starting in Phoenix, AZ).
Preference: Low support burden, good manufacturing fit with current equipment, clear customer targeting.

Core Pipeline (existing)

Scanners: marketplace, search volume (DataForSEO Google Ads), trends, X, Printables/Cults, local service keywords (Phoenix)
Scoring: Demand score, Competition score, Manufacturing Fit / Customer Clarity, Opportunity score
Reddit is unreliable — treat as optional/low weight
Weekly local schedule already exists (com.demandmonitor.weekly)

New Priority Goals

Make all gathered data easy to interpret and actionable
Push results into Google Sheets (my Google account)
Include charts/graphs that highlight key findings
Fully automate the weekly run and export
Create a clear Dashboard that answers: “What should I work on or sell next?”

Google Sheets Vision

One master spreadsheet
Tabs: Dashboard, Product Rankings, Search Volume, Local Service (Phoenix), Marketplace, History, Config
Dashboard must show:
Top opportunities this week
Demand vs Fit view
Key charts (bar, trend, ranking)
Simple “Action This Week” callouts

Data should be clean, timestamped, and historical where useful

Automation Preference

Keep weekly cadence
Prefer extending the existing local weekly job first (simplest)
End of pipeline should call an export_to_sheets.py script
Use Google Service Account for reliable, non-interactive auth

Collaboration Rules (Grok + Claude)

Claude owns: architecture, data model, Dashboard design, scoring review, documentation, final review
Grok owns: implementation in the repo, exporters, automation scripts, charts setup code, integration
Both always read this Project Brief first
Avoid both agents editing the same files at the same time
Prefer clear specs → implement → review cycles

Success Looks Like
Every Monday I can open one Google Sheet and immediately see the strongest product opportunities, local service demand signals, and what is worth acting on — without digging through JSON files.