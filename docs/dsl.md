# Skeleton DSL reference

The Skeleton DSL (`.skel`) is a small, Rust-flavoured, block-structured
front-end for ConcIR. Its meaning is exactly the meaning of the ConcIR program
it lowers to (`skelnet lower`); it has no independent semantics. Constructs
outside the subset are rejected at parse time with `S0xx`, not deferred to the
backend.

- Locks are **lexically scoped**: `lock m { ... }` releases `m` on block exit,
  including `return`/`break`/`continue`. There is no `unlock`.
- A `condvar` is bound to exactly one mutex at declaration.
- provides/requires are computed by lowering; they are never written by hand.
- The entry point is fixed at `main::main`.

## Lexical structure

- Identifiers `[A-Za-z_][A-Za-z0-9_]*`.
- Integers (unsigned lexically; `-` is a unary operator in expressions).
- Strings `"..."` with `\"`, `\\`, `\n`.
- `//` line comments; whitespace is insignificant.
- Keywords: `skeleton module mutex condvar for semaphore channel cap shared
  guarded_by atomic fn extern let lock permit scope spawn if else while loop
  break continue return compute reads writes true false Bool Int`.
- Out-of-subset reserved words (produce `S002` + hint): `rwlock RwLock
  read_lock write_lock async await select unlock release acquire drop unsafe
  Arc Float String struct enum match thread`.

## Grammar (EBNF — authoritative)

```ebnf
File        = "skeleton", Ident, ";", ( { Item } | ModuleDecl, { ModuleDecl } ) ;
ModuleDecl  = "module", Ident, "{", { Item }, "}" ;
Item        = { Tag }, ( ResourceDecl | FnDecl | ExternFn ) ;
Tag         = "@", Ident ;                       (* e.g. @R3; must match R[0-9]+ else S109 *)

ResourceDecl
  = "mutex", Ident, ";"
  | "condvar", Ident, "for", Name, ";"
  | "semaphore", Ident, "=", IntLit, ";"                     (* initial permits >= 0 *)
  | "channel", Ident, ":", Type, "cap", IntLit, ";"          (* cap 0 = rendezvous *)
  | "shared", Ident, ":", Type, "=", Literal, [ "guarded_by", Name ], ";"
  | "atomic", Ident, ":", Type, "=", Literal, ";" ;

Type        = "Bool" | "Int" | "Int", "[", IntLit, "..=", IntLit, "]" ;

FnDecl      = "fn", Ident, "(", [ Param, { ",", Param } ], ")", [ "->", Type ], Block ;
ExternFn    = "extern", "fn", Ident, "(", ")", ";" ;         (* opaque function: empty body *)
Param       = Ident, ":", Type ;

Block       = "{", { Stmt }, "}" ;
Stmt        = { Tag }, StmtCore ;
StmtCore
  = "lock", Name, Block
  | "permit", Name, Block
  | "scope", "{", { "spawn", Name, "(", ")", ";" }, "}"
  | "if", Expr, Block, [ "else", ( Block | IfStmt ) ]
  | "while", Expr, Block
  | "loop", Block
  | "break", ";" | "continue", ";"
  | "return", [ Expr ], ";"
  | "compute", StringLit, [ "reads", "(", NameList, ")" ], [ "writes", "(", NameList, ")" ], ";"
  | "let", Ident, [ ":", Type ], "=", Rhs, ";"
  | Name, "=", Expr, ";"                                     (* local or shared assignment *)
  | Name, ".", Method, ";"                                   (* value-returning-free method stmt *)
  | Call, ";" ;
IfStmt      = "if", Expr, Block, [ "else", ( Block | IfStmt ) ] ;

Rhs         = Expr
            | Name, ".", "recv", "(", ")"
            | Name, ".", "load", "(", ")"
            | Name, ".", "cas", "(", Expr, ",", Expr, ")"
            | "spawn", Call
            | Call ;
Method      = "send", "(", Expr, ")" | "recv", "(", ")" | "store", "(", Expr, ")"
            | "notify_one", "(", ")" | "notify_all", "(", ")" | "wait", "(", ")"
            | "post", "(", ")" | "take", "(", ")" | "join", "(", ")" ;
Call        = Name, "(", [ Expr, { ",", Expr } ], ")" ;
Name        = Ident, [ "::", Ident ] ;
NameList    = Name, { ",", Name } ;

(* expressions = the ConcIR expression subset, minus Struct *)
Expr        = AddExpr, [ CmpOp, AddExpr ] ;
CmpOp       = "==" | "!=" | "<" | "<=" | ">" | ">=" ;
AddExpr     = MulExpr, { ( "+" | "-" ), MulExpr } ;
MulExpr     = Unary, { ( "*" | "/" | "%" ), Unary } ;
Unary       = [ "-" ], Atom ;
Atom        = IntLit | "true" | "false" | Name | "(", Expr, ")" ;
```

This matches `crates/skel/src/parser.rs` and `docs/concir/ebnf.md` (ConcIR
expressions, without Struct).

## Front-end checks

| code | meaning |
| --- | --- |
| S001 | lexical error |
| S002 | out-of-subset construct (with a hint) |
| S003 | syntax error (expected token set) |
| S101 | undefined name |
| S102 | duplicate definition |
| S103 | resource kind / operation mismatch |
| S104 | `cv.wait()` outside the `lock` of its bound mutex |
| S105 | `break`/`continue` outside a loop |
| S106 | `scope` spawn target is not a `fn` |
| S107 | `.join()` on a non-spawn handle |
| S108 | literal/type mismatch, bounded `Int` initializer out of range, bad arity |
| S109 | invalid tag (not `R<n>`) |
| S201 (warning) | a requirement id has no `@R` annotation (`--reqs`) |
| S202 (warning) | `@R<n>` references an unknown requirement id (`--reqs`) |

Protected-variable access without a lock (E309), missing `join` (E401),
non-terminating loops (E605), etc. are left to the ConcIR verifier and surfaced
through remapped feedback.

## Examples

```skel
skeleton abba_2lock;

mutex a;
mutex b;

@R1
fn main() { scope { spawn t1(); spawn t2(); } }

@R2 @R4
fn t1() { lock a { lock b { compute "update both records"; } } }

@R3 @R4
fn t2() { lock a { lock b { compute "update both records"; } } }
```

```skel
skeleton bare_wait;

mutex m;
condvar cv for m;
shared ready: Bool = false guarded_by m;

fn main() { scope { spawn waiter(); spawn notifier(); } }

@R4 @R6
fn waiter() { lock m { while ready == false { cv.wait(); } } }

@R3
fn notifier() { lock m { ready = true; cv.notify_one(); } }
```

## CLI

```
skelnet parse  <f.skel> [--json]
skelnet fmt    <f.skel> [--check]
skelnet lower  <f.skel> -o <f.cir.json> [--map <f.map.json>]
skelnet check  <f.skel> [--reqs requirements.json] [--json]
skelnet verify <f.skel> <contract.json> [--engine petri|interp] [--json]
skelnet codegen <f.skel> [--out <dir>]
skelnet adhere <f.skel> <main.rs> [--json]
```

Exit codes: `0` pass, `1` diagnostics/verification failure, `2` usage/IO.
