"use strict";
document.addEventListener("DOMContentLoaded", function () {
  var root = document.querySelector("[data-semester-simulator]");
  if (!root) return;
  var sliders = Array.from(root.querySelectorAll("input[type=range]"));
  var target = root.querySelector("[data-overall-target]");
  var apply = root.querySelector("[data-overall-apply]");
  var attendance = { shortages: Number(root.dataset.shortages), watch: root.dataset.watchAttendance === "true", pending: root.dataset.attendancePending === "true" };
  var baseline = sliders.map(function (slider) { return Number(slider.dataset.courseBaseline); });
  var initial = PerformanceCore.evaluateCourses(baseline, attendance);
  function marks() { return sliders.map(function (slider) { return Number(slider.value); }); }
  function update() {
    var values = marks();
    var result = PerformanceCore.evaluateCourses(values, attendance);
    sliders.forEach(function (slider, index) {
      var label = slider.closest("label");
      label.querySelector("[data-course-output]").textContent = values[index].toFixed(2);
      label.querySelector("[data-course-bar]").style.width = values[index] + "%";
      label.querySelector("[data-course-grade]").textContent = result.grades[index];
    });
    root.querySelector("[data-overall-average]").textContent = result.percentage.toFixed(2);
    root.querySelector("[data-overall-grade]").textContent = result.grade;
    var difference = result.percentage - initial.percentage;
    root.querySelector("[data-overall-change]").textContent = (difference >= 0 ? "+" : "") + difference.toFixed(2);
    root.querySelector("[data-overall-pass]").textContent = result.passed ? "Every course ≥ 40" : result.failed + " course(s) below 40";
    var status = root.querySelector("[data-overall-status]");
    status.textContent = result.status;
    status.className = "badge " + (result.status === "At Risk" ? "badge-danger" : result.status === "Watchlist" ? "badge-warning" : result.status === "On Track" ? "badge-success" : "badge-neutral");
    var plan = PerformanceCore.courseGoal(values, Number(target.value));
    root.querySelector("[data-overall-message]").textContent = plan.needed ?
      "Add " + plan.needed.toFixed(2) + " marks across courses to reach at least " + target.value + "% and keep every course at 40 or above." : "The target and course pass minimum are already met.";
    apply.disabled = !plan.needed;
    root.querySelector("[data-overall-live]").textContent = "Projected average " + result.percentage.toFixed(2) + " percent, grade " + result.grade + ", " + result.status + ".";
  }
  sliders.forEach(function (slider) { slider.addEventListener("input", update); });
  target.addEventListener("change", update);
  apply.addEventListener("click", function () {
    var plan = PerformanceCore.courseGoal(marks(), Number(target.value));
    sliders.forEach(function (slider, index) { slider.value = String(plan.marks[index]); });
    update();
  });
  root.querySelector("[data-overall-reset]").addEventListener("click", function () {
    sliders.forEach(function (slider, index) { slider.value = String(baseline[index]); });
    target.value = "80";
    update();
  });
  update();
});
