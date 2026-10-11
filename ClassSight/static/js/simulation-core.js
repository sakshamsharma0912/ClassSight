(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PerformanceCore = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  var caps = [5, 5, 15, 10, 10, 15, 40];
  var bands = [["O", 90], ["A+", 80], ["A", 70], ["B+", 60], ["B", 50], ["C", 40], ["F", 0]];
  function evaluate(values) {
    if (!Array.isArray(values) || values.length !== 7) throw new Error("Seven components are required.");
    var cents = values.map(function (value, index) {
      if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > caps[index]) {
        throw new Error("Component marks exceed their allowed range.");
      }
      return Math.round(value * 100);
    });
    var total = cents.reduce(function (sum, value) { return sum + value; }, 0);
    var internal = cents.slice(0, 6).reduce(function (sum, value) { return sum + value; }, 0);
    return { total: total / 100, percentage: total / 100, internal: internal / 100,
      grade: bands.find(function (band) { return total >= band[1] * 100; })[0] };
  }
  function goal(values, target) {
    var result = evaluate(values);
    if (!Number.isFinite(target) || target < 0 || target > 100) throw new Error("Target must be between 0 and 100.");
    var required = Math.max(0, Math.round(target * 100) - Math.round(result.internal * 100)) / 100;
    return { requiredFinal: required, feasible: required <= 40, internalImprovement: Math.max(0, required - 40) };
  }
  function courseCents(marks) {
    if (!Array.isArray(marks) || !marks.length || marks.length > 50) throw new Error("Choose 1–50 course totals.");
    return marks.map(function (value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 100 ||
          Math.abs(value * 100 - Math.round(value * 100)) > 0.000001) throw new Error("Course totals must be between 0 and 100 with two decimal places.");
      return Math.round(value * 100);
    });
  }
  function evaluateCourses(marks, attendance) {
    var cents = courseCents(marks);
    var sum = cents.reduce(function (a, b) { return a + b; }, 0);
    var failed = cents.filter(function (value) { return value < 4000; }).length;
    attendance = attendance || {};
    var risk = failed > 0 || sum < 5000 * cents.length || Boolean(attendance.shortages);
    var watch = sum < 6500 * cents.length || Boolean(attendance.watch);
    return { percentage: sum / (100 * cents.length), total: sum / 100,
      grade: bands.find(function (band) { return sum >= band[1] * 100 * cents.length; })[0],
      grades: cents.map(function (value) { return bands.find(function (band) { return value >= band[1] * 100; })[0]; }),
      failed: failed, passed: failed === 0,
      status: risk ? "At Risk" : watch ? "Watchlist" : attendance.pending ? "Pending" : "On Track" };
  }
  function courseGoal(marks, target) {
    var cents = courseCents(marks);
    if (!Number.isFinite(target) || target < 0 || target > 100) throw new Error("Target must be between 0 and 100.");
    var initial = cents.reduce(function (a, b) { return a + b; }, 0);
    var planned = cents.map(function (value) { return Math.max(value, 4000); });
    var required = Math.ceil(target * 100 * cents.length - 0.000001);
    var total = planned.reduce(function (a, b) { return a + b; }, 0);
    // Allocate exact centimarks without decreasing an existing mark or crossing 100.
    while (total < required) {
      var lowest = Math.min.apply(null, planned);
      planned[planned.indexOf(lowest)] += 1;
      total += 1;
    }
    return { marks: planned.map(function (value) { return value / 100; }),
      needed: (total - initial) / 100, percentage: total / (100 * planned.length) };
  }
  return { caps: caps, evaluate: evaluate, goal: goal, evaluateCourses: evaluateCourses, courseGoal: courseGoal };
});
