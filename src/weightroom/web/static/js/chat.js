/* chat.js — the new-conversation composer's two conveniences (row WX4).
 *
 * Loaded only by chat.html, and only ever a convenience: without it both backends' fieldsets are
 * visible and the tool allowlist is the free-text input it has always been. It writes nothing but
 * form values, and never omits the `tools` field — an omitted allowlist means *every* configured
 * tool to PromptCadence (services/chat_promptcadence.py), so "allow all" writes the names.
 */
(function () {
  "use strict";

  var backend = document.getElementById("chat-backend");
  if (backend) {
    var show = function () {
      document.querySelectorAll("[data-backend]").forEach(function (group) {
        group.hidden = group.getAttribute("data-backend") !== backend.value;
      });
    };
    backend.addEventListener("change", show);
    show();
  }

  var list = document.getElementById("chat-tools");
  var pick = document.getElementById("chat-tool-pick");
  var all = document.getElementById("chat-tools-all");
  if (!list) { return; }

  var names = function () {
    return list.value.split(",").map(function (one) { return one.trim(); }).filter(Boolean);
  };

  if (pick) {
    pick.addEventListener("change", function () {
      var chosen = pick.value;
      var have = names();
      if (chosen && have.indexOf(chosen) === -1) { list.value = have.concat([chosen]).join(", "); }
      pick.value = "";
    });
  }

  if (all) {
    var before = "";
    all.addEventListener("change", function () {
      if (all.checked) {
        before = list.value;
        list.value = all.getAttribute("data-all") || "";
      } else {
        list.value = before;
      }
    });
  }
})();

/* The history table's rows open their conversation on a click anywhere in the row — a
 * convenience on top of the title's own link (row WY7), which still works with no JS and the
 * keyboard. A click already headed somewhere (the title link itself) is left alone. */
(function () {
  "use strict";

  var table = document.querySelector('table[data-table="chat-history"]');
  if (!table) { return; }

  table.addEventListener("click", function (event) {
    if (event.target.closest("a")) { return; }
    var row = event.target.closest("tbody tr");
    if (!row) { return; }
    var link = row.querySelector("a[href]");
    if (link) { window.location.href = link.getAttribute("href"); }
  });
})();
