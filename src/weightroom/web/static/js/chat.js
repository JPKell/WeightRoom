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
