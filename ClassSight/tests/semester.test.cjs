const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const core=require('../static/js/simulation-core.js');

test('overall projection handles seven courses and exact average grade boundaries',()=>{
 const result=core.evaluateCourses([80,80,80,80,80,80,79.99]);
 assert.equal(result.grade,'A');assert.ok(result.percentage<80);
 assert.equal(core.evaluateCourses(Array(7).fill(100)).grade,'O');
});
test('a strong average cannot conceal a failed course or attendance shortage',()=>{
 assert.equal(core.evaluateCourses([39.99,100,100]).passed,false);
 assert.equal(core.evaluateCourses([100,100],{shortages:1}).status,'At Risk');
 assert.equal(core.evaluateCourses([80,80],{watch:true}).status,'Watchlist');
 assert.equal(core.evaluateCourses([80,80],{pending:true}).status,'Pending');
 assert.equal(core.evaluateCourses([49.99,49.99]).status,'At Risk');
 assert.equal(core.evaluateCourses([64.99,64.99]).status,'Watchlist');
 assert.equal(core.evaluateCourses([65,65]).status,'On Track');
});
test('balanced plans preserve high marks, raise weak courses and reach the goal',()=>{
 const before=[20,40,90,100,60,75,80],plan=core.courseGoal(before,80);
 assert.ok(plan.percentage>=80);
 assert.ok(plan.marks.every((mark,i)=>mark>=before[i]&&mark>=40&&mark<=100));
 assert.equal(plan.marks[3],100);assert.equal(core.evaluateCourses(plan.marks).passed,true);
});
test('an average goal already met still repairs failing courses',()=>{
 const plan=core.courseGoal([10,100,100],40);
 assert.deepEqual(plan.marks,[40,100,100]);assert.equal(plan.needed,30);
 assert.deepEqual(core.courseGoal([80,90],60).marks,[80,90]);
});
test('fractional goals never rely on rounded display percentages',()=>{
 const plan=core.courseGoal([60,60,60],66.67);
 assert.equal(Math.round(plan.marks.reduce((a,b)=>a+b,0)*100),20001);
 assert.ok(plan.percentage>=66.67);
});
test('full headroom reaches 100 and invalid shapes or precision are rejected',()=>{
 assert.deepEqual(core.courseGoal(Array(7).fill(0),100).marks,Array(7).fill(100));
 for(const bad of [[],[NaN],[Infinity],[-1],[100.01],[1.001]])assert.throws(()=>core.evaluateCourses(bad));
 for(const target of [-1,100.01,NaN])assert.throws(()=>core.courseGoal([70],target));
});
test('semester sliders, target, apply and reset update independent live outputs',()=>{
 function element(value=''){return {value,textContent:'',style:{},dataset:{},disabled:false,listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}};}
 const outputs={};
 for(const name of ['target','apply','average','grade','change','pass','status','message','live','reset'])outputs['[data-overall-'+name+']']=element();
 outputs['[data-overall-target]'].value='80';
 const sliders=[50,60,70,80,90,100,40].map(mark=>{
  const input=element(String(mark));input.dataset.courseBaseline=String(mark);
  const local={'[data-course-output]':element(),'[data-course-bar]':element(),'[data-course-grade]':element()};
  input.closest=()=>({querySelector:selector=>local[selector]});input.local=local;return input;
 });
 const root={dataset:{shortages:'1',watchAttendance:'false',attendancePending:'false'},querySelector:s=>outputs[s],querySelectorAll:()=>sliders};
 vm.runInNewContext(fs.readFileSync('static/js/semester-simulator.js','utf8'),{PerformanceCore:core,document:{querySelector:()=>root,addEventListener:(_type,fn)=>fn()}});
 assert.equal(outputs['[data-overall-average]'].textContent,'70.00');
 sliders[0].value='100';sliders[0].listeners.input();
 assert.equal(sliders[0].local['[data-course-output]'].textContent,'100.00');
 assert.equal(sliders[0].local['[data-course-bar]'].style.width,'100%');
 outputs['[data-overall-apply]'].listeners.click();
 assert.ok(Number(outputs['[data-overall-average]'].textContent)>=80);
 assert.equal(outputs['[data-overall-status]'].textContent,'At Risk');
 assert.ok(outputs['[data-overall-apply]'].disabled);
 outputs['[data-overall-reset]'].listeners.click();
 assert.equal(outputs['[data-overall-average]'].textContent,'70.00');
 assert.deepEqual(sliders.map(x=>Number(x.value)),[50,60,70,80,90,100,40]);
 outputs['[data-overall-target]'].value='100';outputs['[data-overall-target]'].listeners.change();
 outputs['[data-overall-apply]'].listeners.click();
 assert.equal(outputs['[data-overall-grade]'].textContent,'O');
 assert.ok(outputs['[data-overall-live]'].textContent.includes('100.00'));
});
