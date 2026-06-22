// Family portal child form: progressive enhancement for the Schools inline
// formset. The form works without JS (extra slots are just always-visible
// blanks Django ignores when empty); with JS we hide spare slots behind an
// "Add a school" button and let "Remove" clear + re-hide a slot.
//
// The care-schedule day toggles and checkbox visuals are pure CSS (:has), so
// they need no script here.
(function () {
  "use strict";

  function init() {
    var container = document.getElementById("fp-schools");
    if (!container) {
      return;
    }
    var addBtn = document.getElementById("fp-add-school");
    var emptyNote = document.getElementById("fp-noschools");

    function blocks() {
      return Array.prototype.slice.call(
        container.querySelectorAll(".fp-school"),
      );
    }

    function visibleCount() {
      return blocks().filter(function (b) {
        return !b.hidden;
      }).length;
    }

    function refresh() {
      var hasVisible = visibleCount() > 0;
      if (emptyNote) {
        emptyNote.hidden = hasVisible;
      }
      if (addBtn) {
        // Disable "Add" once every slot is showing.
        var spare = blocks().some(function (b) {
          return b.hidden;
        });
        addBtn.disabled = !spare;
        addBtn.style.opacity = spare ? "" : "0.5";
        addBtn.style.cursor = spare ? "" : "not-allowed";
      }
    }

    if (addBtn) {
      addBtn.addEventListener("click", function () {
        var next = blocks().filter(function (b) {
          return b.hidden;
        })[0];
        if (!next) {
          return;
        }
        next.hidden = false;
        // Clear any stale DELETE flag the slot may carry.
        var del = next.querySelector("input[type=checkbox][name$='-DELETE']");
        if (del) {
          del.checked = false;
        }
        var first = next.querySelector("input:not([type=hidden]):not([type=checkbox]), select");
        if (first) {
          first.focus();
        }
        refresh();
      });
    }

    container.addEventListener("click", function (event) {
      var remove = event.target.closest(".fp-school__remove");
      if (!remove) {
        return;
      }
      event.preventDefault();
      var block = remove.closest(".fp-school");
      if (!block) {
        return;
      }
      // Tell Django to drop this row (no-op for an empty/unsaved slot) and
      // clear its inputs so a re-hidden slot doesn't resubmit stale data.
      var del = block.querySelector("input[type=checkbox][name$='-DELETE']");
      if (del) {
        del.checked = true;
      }
      block.querySelectorAll("input:not([type=hidden]), select, textarea").forEach(
        function (field) {
          if (field.type === "checkbox") {
            return;
          }
          field.value = "";
        },
      );
      block.hidden = true;
      refresh();
    });

    refresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
