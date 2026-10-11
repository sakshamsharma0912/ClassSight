"use strict";
document.addEventListener("DOMContentLoaded", function () {
  var sidebar = document.getElementById("sidebar");
  var toggle = document.getElementById("nav-toggle");
  var backdrop = document.getElementById("sidebar-backdrop");
  function setNavigation(open) {
    if (!sidebar || !toggle || !backdrop) return;
    sidebar.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    backdrop.hidden = !open;
    document.body.classList.toggle("nav-open", open);
  }
  if (toggle) toggle.addEventListener("click", function () {
    setNavigation(toggle.getAttribute("aria-expanded") !== "true");
  });
  if (backdrop) backdrop.addEventListener("click", function () { setNavigation(false); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") setNavigation(false);
  });
  window.addEventListener("resize", function () {
    if (window.innerWidth >= 1024) setNavigation(false);
  });

  document.querySelectorAll("[data-dialog]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      var dialog = document.getElementById(link.dataset.dialog);
      if (dialog && typeof dialog.showModal === "function") {
        event.preventDefault();
        dialog.showModal();
      }
    });
  });
  document.querySelectorAll("[data-close-dialog]").forEach(function (button) {
    button.addEventListener("click", function () { button.closest("dialog").close(); });
  });
  document.querySelectorAll("dialog").forEach(function (dialog) {
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) {
        var rect = dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right ||
            event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
      }
    });
  });
  document.querySelectorAll(".notice-dismiss").forEach(function (button) {
    button.addEventListener("click", function () { button.closest(".notice").remove(); });
  });
  document.querySelectorAll("[data-password]").forEach(function (button) {
    button.addEventListener("click", function () {
      var field = document.getElementById(button.dataset.password);
      var show = field.type === "password";
      field.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      button.setAttribute("aria-pressed", String(show));
    });
  });
  document.querySelectorAll("[data-copy-input]").forEach(function (button) {
    button.addEventListener("click", async function () {
      var field = document.getElementById(button.dataset.copyInput);
      var status = button.parentElement.querySelector("[data-copy-status]");
      if (!field) return;
      try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(field.value);
        if (status) status.textContent = "Activation link copied.";
      } catch (_error) {
        field.focus();
        field.select();
        if (status) status.textContent = "Link selected. Press Ctrl+C or use your device's Copy action.";
      }
    });
  });
  var file = document.getElementById("csv-file");
  if (file) file.addEventListener("change", function () {
    document.getElementById("csv-filename").textContent = file.files.length ? file.files[0].name : "No file selected";
  });

  var gradeBands = [["O", 9000], ["A+", 8000], ["A", 7000], ["B+", 6000], ["B", 5000], ["C", 4000], ["F", 0]];
  function grade(total) {
    return gradeBands.find(function (band) { return total >= band[1]; })[0];
  }
  function centimarks(input) {
    if (!input.value.trim()) return null;
    if (!/^\d{1,3}(?:\.\d{1,2})?$/.test(input.value) || !input.validity.valid) return NaN;
    var parts = input.value.split(".");
    return Number(parts[0]) * 100 + Number((parts[1] || "").padEnd(2, "0"));
  }
  document.querySelectorAll("[data-mark-row]").forEach(function (row) {
    var inputs = Array.from(row.querySelectorAll(".mark-input"));
    if (!inputs.length) return;
    function update() {
      var marks = inputs.map(centimarks);
      var invalid = marks.some(Number.isNaN);
      var complete = marks.every(function (mark) { return mark !== null && !Number.isNaN(mark); });
      var subtotal = marks.slice(0, 6).reduce(function (sum, mark) { return sum + (mark || 0); }, 0);
      var total = marks.reduce(function (sum, mark) { return sum + (mark || 0); }, 0);
      row.querySelector("[data-internal-total]").textContent = invalid ? "Invalid" : (subtotal / 100).toFixed(2);
      row.querySelector("[data-internal-state]").textContent =
        marks.slice(0, 6).every(function (mark) { return mark !== null && !Number.isNaN(mark); }) ? "Complete" : "Partial";
      row.querySelector("[data-mark-total]").textContent = invalid ? "Invalid" : complete ? (total / 100).toFixed(2) : "Pending";
      row.querySelector("[data-mark-grade]").textContent = invalid ? "Invalid" : complete ? grade(total) : "Pending";
    }
    inputs.forEach(function (input) { input.addEventListener("input", update); });
    update();
  });

  var sessionForm = document.querySelector("[data-session-form]");
  if (sessionForm) {
    var hoursInput = document.getElementById("session-hours");
    var entries = Array.from(sessionForm.querySelectorAll(".session-attended"));
    var previousHours = Number(hoursInput.value);
    function sessionHours() { return Math.max(1, Math.min(12, Number(hoursInput.value) || 1)); }
    hoursInput.addEventListener("input", function () {
      if (!hoursInput.validity.valid) return;
      var hours = sessionHours();
      entries.forEach(function (input) {
        input.max = String(hours);
        input.value = Number(input.value) === previousHours ? hours : Math.min(Number(input.value), hours);
      });
      previousHours = hours;
    });
    function setEntries(value) {
      entries.forEach(function (input) { input.value = String(value); });
    }
    sessionForm.querySelector("[data-all-present]").addEventListener("click", function () { setEntries(sessionHours()); });
    sessionForm.querySelector("[data-all-absent]").addEventListener("click", function () { setEntries(0); });
    sessionForm.querySelectorAll("[data-present]").forEach(function (button) {
      button.addEventListener("click", function () { button.closest("tr").querySelector(".session-attended").value = String(sessionHours()); });
    });
    sessionForm.querySelectorAll("[data-absent]").forEach(function (button) {
      button.addEventListener("click", function () { button.closest("tr").querySelector(".session-attended").value = "0"; });
    });
  }
  document.querySelectorAll("[data-unsaved-form]").forEach(function (form) {
    var dirty = false;
    form.addEventListener("input", function () { dirty = true; });
    form.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (event) {
      if (dirty) { event.preventDefault(); event.returnValue = ""; }
    });
  });
});
