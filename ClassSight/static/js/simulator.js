"use strict";
document.addEventListener("DOMContentLoaded", function () {
  var simulator = document.querySelector("[data-simulator]");
  if (!simulator) return;
  var inputs = Array.from(simulator.querySelectorAll('input[type="range"]'));
  var target = document.getElementById("target-percentage");
  var apply = document.getElementById("apply-goal");
  var message = document.getElementById("goal-message");
  function values() { return inputs.map(function (input) { return Number(input.value); }); }
  function update() {
    var marks = values();
    var result = PerformanceCore.evaluate(marks);
    inputs.forEach(function (input) {
      simulator.querySelector('[data-output="' + input.dataset.key + '"]').textContent = Number(input.value).toFixed(2);
    });
    document.getElementById("projected-percentage").textContent = result.percentage.toFixed(2);
    document.getElementById("projected-grade").textContent = result.grade;
    document.getElementById("projected-internal").textContent = result.internal.toFixed(2);
    var plan = PerformanceCore.goal(marks, Number(target.value));
    message.textContent = plan.feasible ?
      "Final exam required: " + plan.requiredFinal.toFixed(2) + " / 40 to reach " + target.value + "%." :
      "Requires " + plan.internalImprovement.toFixed(2) + " more internal marks, even with 40 / 40 in the final exam.";
    apply.disabled = !plan.feasible;
    apply.title = plan.feasible ? "Set the final-exam slider to the required mark" : "Increase the internal component marks to make this target feasible";
    document.getElementById("simulation-live").textContent =
      "Projected percentage " + result.percentage.toFixed(2) + " percent, grade " + result.grade + ".";
  }
  inputs.forEach(function (input) { input.addEventListener("input", update); });
  target.addEventListener("change", update);
  apply.addEventListener("click", function () {
    var plan = PerformanceCore.goal(values(), Number(target.value));
    if (plan.feasible) { inputs[6].value = String(plan.requiredFinal); update(); }
  });
  document.getElementById("reset-simulation").addEventListener("click", function () {
    inputs.forEach(function (input) { input.value = input.dataset.baseline; });
    update();
  });
  update();
});
