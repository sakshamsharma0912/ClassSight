const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const core = require("../static/js/simulation-core.js");

test("the seven component caps total exactly 100 in the required order", () => {
  assert.deepEqual(core.caps, [5, 5, 15, 10, 10, 15, 40]);
  assert.deepEqual(core.evaluate(core.caps), { total: 100, percentage: 100, internal: 60, grade: "O" });
});

for (const [total, expected] of [[0,"F"],[39.99,"F"],[40,"C"],[49.99,"C"],[50,"B"],[59.99,"B"],
  [60,"B+"],[69.99,"B+"],[70,"A"],[79.99,"A"],[80,"A+"],[89.99,"A+"],[90,"O"],[100,"O"]]) {
  test("grade boundary at " + total, () => {
    const internal = Math.min(60, total);
    const values = core.caps.slice(0,6).map(cap => internal * cap / 60);
    // Match totals exactly at centimark precision by correcting the sixth entry.
    const subtotal = values.slice(0,5).reduce((sum, v) => sum + Math.round(v * 100), 0);
    values[5] = (Math.round(internal * 100) - subtotal) / 100;
    values.push(Math.max(0, total - 60));
    assert.equal(core.evaluate(values).grade, expected);
    assert.equal(core.evaluate(values).total, total);
  });
}

test("bad shapes, out-of-range values, and non-finite marks are rejected", () => {
  for (const values of [[],[1,2,3],[-1,0,0,0,0,0,0],[5.01,0,0,0,0,0,0],
    [0,0,0,0,0,0,40.01],[NaN,0,0,0,0,0,0],[Infinity,0,0,0,0,0,0]]) {
    assert.throws(() => core.evaluate(values));
  }
});

test("goal seeker respects the final exam cap and uses centimarks", () => {
  assert.deepEqual(core.goal([4,4,12,8,8,12,0], 80), {
    requiredFinal:32, feasible:true, internalImprovement:0 });
  assert.deepEqual(core.goal([0,0,0,0,0,0,0], 80), {
    requiredFinal:80, feasible:false, internalImprovement:40 });
  assert.equal(core.goal([5,5,15,10,10,15,0],50).requiredFinal, 0);
  assert.equal(core.goal([4.99,5,15,10,10,15,0],80).requiredFinal, 20.01);
});

// Exercise the actual controller scripts against event-driven DOM fixtures.
// These are JavaScript integration checks, not a substitute for real-browser QA.
class Element {
  constructor(value = "") { this.value=String(value); this.textContent=""; this.listeners={}; this.dataset={}; this.attrs={}; this.classes=new Set(); this.hidden=false; this.disabled=false; this.refs={}; this.lists={}; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  emit(name, event={}) { for (const fn of this.listeners[name] || []) fn({target:this,...event}); }
  setAttribute(key, value) { this.attrs[key]=String(value); }
  getAttribute(key) { return this.attrs[key]; }
  querySelector(key) { return this.refs[key] || null; }
  querySelectorAll(key) { return this.lists[key] || []; }
  closest(key) { return this.refs["closest:"+key]; }
  classList={ toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name) };
  get validity() {
    const number=Number(this.value);
    return {valid: this.value === "" || Number.isFinite(number) &&
      (this.min === undefined || number >= Number(this.min)) && (this.max === undefined || number <= Number(this.max))};
  }
}

test("activation-link copy reports success and offers a usable clipboard fallback", async () => {
  for (const allowed of [true, false]) {
    const document = new Element(), window = new Element();
    document.body = new Element();
    const field = new Element("http://localhost:5000/student/activate/example-token");
    field.focus = () => { field.focused = true; };
    field.select = () => { field.selected = true; };
    const button = new Element(), panel = new Element(), status = new Element();
    button.dataset.copyInput = "activation-link";
    button.parentElement = panel;
    panel.refs["[data-copy-status]"] = status;
    document.lists["[data-copy-input]"] = [button];
    document.getElementById = id => id === "activation-link" ? field : null;
    let copied = null;
    const navigator = {clipboard:{writeText:async value => {
      if (!allowed) throw new Error("Clipboard permission denied");
      copied = value;
    }}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../static/js/main.js"),"utf8"), {document,window,navigator});
    document.emit("DOMContentLoaded");
    await button.listeners.click[0]({target:button});
    if (allowed) {
      assert.equal(copied, field.value);
      assert.equal(status.textContent, "Activation link copied.");
    } else {
      assert.equal(copied, null);
      assert.equal(field.focused, true);
      assert.equal(field.selected, true);
      assert.match(status.textContent, /Ctrl\+C/);
    }
  }
});

test("slider, target, apply-goal and reset controls recalculate the live projection", () => {
  const keys=["assignment_1","assignment_2","internal_exam_1","mini_project","practical","internal_exam_2","university_final"];
  const initial=[4,4,12,8,8,12,20];
  const inputs=initial.map((value,i) => { const e=new Element(value); e.dataset={key:keys[i],baseline:String(value)}; return e; });
  const root=new Element();
  root.lists['input[type="range"]']=inputs;
  keys.forEach(key => { root.refs['[data-output="'+key+'"]']=new Element(); });
  const ids={};
  ["projected-percentage","projected-grade","projected-internal","goal-message","apply-goal",
   "target-percentage","reset-simulation","simulation-live"].forEach(id => { ids[id]=new Element(); });
  ids["target-percentage"].value="80";
  const document={querySelector:s => s === "[data-simulator]" ? root : null,
    getElementById:id => ids[id],addEventListener:(_event, fn) => fn()};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../static/js/simulator.js"),"utf8"),{
    document,PerformanceCore:core});
  assert.equal(ids["projected-percentage"].textContent,"68.00");
  assert.equal(ids["projected-grade"].textContent,"B+");
  ids["apply-goal"].emit("click");
  assert.equal(inputs[6].value,"32");
  assert.equal(ids["projected-percentage"].textContent,"80.00");
  assert.equal(ids["projected-grade"].textContent,"A+");
  inputs[0].value="0"; inputs[0].emit("input");
  assert.equal(ids["projected-percentage"].textContent,"76.00");
  ids["target-percentage"].value="90"; ids["target-percentage"].emit("change");
  assert.equal(ids["apply-goal"].disabled,true);
  assert.match(ids["goal-message"].textContent,/6\.00 more internal marks/);
  ids["reset-simulation"].emit("click");
  assert.deepEqual(inputs.map(i=>Number(i.value)),initial);
  assert.equal(ids["projected-percentage"].textContent,"68.00");
});

test("navigation, dialogs, password toggle, file label, session controls and mark grid are wired", () => {
  const document=new Element(), window=new Element(), body=new Element();
  document.body=body;
  const ids={sidebar:new Element(),"nav-toggle":new Element(),"sidebar-backdrop":new Element(),
    password:new Element(),"csv-file":new Element(),"csv-filename":new Element(),"session-hours":new Element("1")};
  ids["nav-toggle"].attrs["aria-expanded"]="false";
  ids.password.type="password";
  const dialog=new Element(); dialog.showModal=()=>{dialog.open=true}; dialog.close=()=>{dialog.open=false};
  dialog.getBoundingClientRect=()=>({left:0,right:500,top:0,bottom:500}); ids.dialog=dialog;
  const link=new Element(); link.dataset.dialog="dialog";
  const close=new Element(); close.refs["closest:dialog"]=dialog;
  const passwordToggle=new Element(); passwordToggle.dataset.password="password";
  const notification=new Element(); notification.remove=()=>{notification.removed=true};
  const dismiss=new Element(); dismiss.refs["closest:.notice"]=notification;
  const markRow=new Element();
  const markInputs=core.caps.map(cap => { const input=new Element(cap); input.min=0; input.max=cap; return input; });
  markRow.lists[".mark-input"]=markInputs;
  ["[data-internal-total]","[data-internal-state]","[data-mark-total]","[data-mark-grade]"].forEach(key=>{
    markRow.refs[key]=new Element();
  });
  const session=new Element();
  const entries=[new Element("1"),new Element("1"),new Element("1")];
  session.lists[".session-attended"]=entries;
  session.refs["[data-all-present]"]=new Element(); session.refs["[data-all-absent]"]=new Element();
  const present=new Element(), absent=new Element(), tableRow=new Element();
  tableRow.refs[".session-attended"]=entries[0];
  present.refs["closest:tr"]=tableRow; absent.refs["closest:tr"]=tableRow;
  session.lists["[data-present]"]=[present]; session.lists["[data-absent]"]=[absent];
  document.refs["[data-session-form]"]=session;
  document.lists["[data-dialog]"]=[link]; document.lists["[data-close-dialog]"]=[close];
  document.lists["dialog"]=[dialog]; document.lists[".notice-dismiss"]=[dismiss];
  document.lists["[data-password]"]=[passwordToggle]; document.lists["[data-mark-row]"]=[markRow];
  const grid=new Element(); document.lists["[data-unsaved-form]"]=[grid];
  document.getElementById=id=>ids[id]; window.innerWidth=600;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../static/js/main.js"),"utf8"),{document,window});
  document.emit("DOMContentLoaded");
  ids["nav-toggle"].emit("click"); assert.equal(ids.sidebar.classes.has("is-open"),true);
  assert.equal(ids["nav-toggle"].attrs["aria-expanded"],"true");
  ids["sidebar-backdrop"].emit("click"); assert.equal(ids.sidebar.classes.has("is-open"),false);
  let prevented=false;
  link.emit("click",{preventDefault:()=>{prevented=true}});
  assert.equal(prevented,true); assert.equal(dialog.open,true);
  close.emit("click"); assert.equal(dialog.open,false);
  passwordToggle.emit("click"); assert.equal(ids.password.type,"text");
  passwordToggle.emit("click"); assert.equal(ids.password.type,"password");
  dismiss.emit("click"); assert.equal(notification.removed,true);
  ids["csv-file"].files=[{name:"class-roster.csv"}]; ids["csv-file"].emit("change");
  assert.equal(ids["csv-filename"].textContent,"class-roster.csv");
  assert.equal(markRow.refs["[data-mark-total]"].textContent,"100.00");
  markInputs[6].value=""; markInputs[6].emit("input");
  assert.equal(markRow.refs["[data-mark-grade]"].textContent,"Pending");
  markInputs[0].value="5.01"; markInputs[0].emit("input");
  assert.equal(markRow.refs["[data-mark-total]"].textContent,"Invalid");
  absent.emit("click"); assert.equal(entries[0].value,"0");
  ids["session-hours"].value="3"; ids["session-hours"].emit("input");
  assert.deepEqual(entries.map(e=>Number(e.value)),[0,3,3]);
  present.emit("click"); assert.equal(entries[0].value,"3");
  session.refs["[data-all-absent]"].emit("click");
  assert.deepEqual(entries.map(e=>Number(e.value)),[0,0,0]);
  session.refs["[data-all-present]"].emit("click");
  assert.deepEqual(entries.map(e=>Number(e.value)),[3,3,3]);
  grid.emit("input");
  let blocked=false; window.emit("beforeunload",{preventDefault:()=>{blocked=true}});
  assert.equal(blocked,true);
  grid.emit("submit"); blocked=false;
  window.emit("beforeunload",{preventDefault:()=>{blocked=true}}); assert.equal(blocked,false);
});
