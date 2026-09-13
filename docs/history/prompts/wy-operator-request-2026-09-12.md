# Operator request — 2026-09-12 (the WY arc), verbatim

Recorded as given. The rows in [`roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
schedule every item below.

# WeightRoom
- Chat link moved back into top bar AND kept in left bar.
- Do not include weightroom left bar links on freeweight, loadcoach, ideapress or promptcadence pages
- Overview should show the loadcoach active oldest queued and starving as well as the prompt cadence executing, planning and pending, and freeweight summary
- All logs pages were misunderstood. I want 3 columns. each with 3 rows. The left column is the log level, date, time the middle olumn is app, version, pid and the right column is the message, the logger and the id.
- Settings (apply to all settings pages) The applies, source and value columns should be right aligned. multiple pills in applies column can be stacked and should be given only as much room as they need so there is appropriate room for the key and value columns.
- chat histors should be on a different page under chat. Also the json and delete links are on different y values. should be in line. Add history button there and it shows a table of history and clicking on takes you back to the chat page.
- on the docs page remove the weightroom links from the left nav bar.
- remove the catalog page from the site, no links to it, delete the files
- Telemetry has doubles of charts, the old svg and the new chart.
  - Telemetry history page should be a single page that shows graphs for all the telemetry values measured. Layout should be tight, compact and clean, large values represented with K, M, G etc.
  - ram and vram total are not useful graphs and should just be values. Telemetry history page should also show large bars for current telemetry.
  - line graphs should be beautiful and shade under the line. possible color change the shade under line red for higher levels and green for lower transitioning in the shaded under the line area like a heatmap.
  - Remove any explanitory text and headers. as much info on one screen as possible

# Freeweight
- gives many alerts: application down	freeweight.service	2026-09-13T02:10:36.946Z	2026-09-13T02:11:12.542Z	cleared	running; /api/v1/health answered ReadTimeout: timed out
- models page remove canonical id from table
- All table sorting should show arrows in column for sort. Make them 3 way asc, desc, off, and allow multiple columns to sort at a time. add a number for the sort order
- results page model is using canonical and should just use model name. also remove runtime profile and machine id by default
- evidence page is using canonical id and should just use name. again remove runtime profile and machine by default
- on the database page the links should be at the very top and they do not take you to a page showing the tables, query just shows the admin page.

# LoadCoach

- Models table has the name takeing far to much room. Should be truncated after 30 characters. Maybe make the column width resizable if possible

# Overall changes
- Create a page navbar that sits at the top of the page for navigating subsections. This appears to be implimented differently for different pages. it should be a modular item that lays out the links for that page cleanly. double check that links in that bar are not doubles of links in the left bar. Remove them from the top bar if they are duplicates.
