---
id: execution-model
order: 30
---

<execution model>
A job runs in two phases:
1. Load time: the file is compiled and evaluated top to bottom to collect the pipeline of operations. All operation arguments are evaluated immediately, before any data exists, but operations are not executed.
2. Run time: the runtime calls each operation in order, passing each one the state returned by the previous.

This means:
- Operation execution order may differ from statement declaration order.
- A bare state reference in `get(state.x)` in an operation's arguments is undefined at load time. Defer it with a function, `get(state => state.x)`, or the `$` lazy-state shorthand `get($.x)`, which means `get(state => state.x)`. Note that `$` is readonly and only valid inside an operation's arguments, nowhere else (no `const x = $.y`).
- Never invoke an operation yourself: `post('/x', ...)(state)` bypasses the runtime execution order and is bad practice. It can be tempted to do this when nesting operations within callbacks for iteration. Usually this can be resolved by breaking nesting and moving the operation to the top level.
- `fn()` and `.then()` callbacks must return state. When building a new object, spread the old one (`return { ...state, data: mapped }`) so keys like configuration survive.
- Most operations overwrite `state.data` with its result: after your create/update/post, `state.data` is that call's response, not your input. Copy values you need later onto another state key first.
</execution model>
