/*
 * Referral detail page — progressive enhancement only.
 *
 * Flips the coordinator-notes "All changes saved" hint to "Unsaved changes"
 * once the textarea is edited, mirroring the source design. Without JS the form
 * still posts and saves; the hint simply stays at its server-rendered text.
 */
(function () {
  "use strict";

  document.querySelectorAll("[data-rd-dirty]").forEach(function (field) {
    var hint = document.getElementById(field.getAttribute("data-rd-dirty"));
    if (!hint) {
      return;
    }
    var savedText = hint.textContent;
    var dirtyText = hint.getAttribute("data-dirty-text") || "Unsaved changes";
    field.addEventListener("input", function () {
      hint.textContent = dirtyText;
      hint.classList.add("is-dirty");
    });
    // A reset (e.g. bfcache restore) returns the field to its saved value.
    field.form &&
      field.form.addEventListener("reset", function () {
        hint.textContent = savedText;
        hint.classList.remove("is-dirty");
      });
  });
})();
