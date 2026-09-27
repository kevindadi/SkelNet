//! Map ConcIR diagnostics and counterexamples back to Skeleton DSL positions.
//!
//! Anything that cannot be mapped keeps its original text and is flagged
//! `unmapped: true` (the P3 test asserts this count is zero for the gold suite).

use std::collections::{BTreeMap, HashMap};

use concir::ast::Program;
use concir::diagnostic::ValidationReport;
use concir::explore::VerificationReport;
use concir::sem::outcome::StepLabel;
use serde::Serialize;

use crate::lower::{MapStmt, SourceMap};
use crate::span::SourceFile;

#[derive(Debug, Clone, Serialize)]
pub struct SkelRef {
    pub loc: String,
    pub construct: String,
    pub line: u32,
    pub col: u32,
    pub end_line: u32,
    pub end_col: u32,
    pub reqs: Vec<String>,
}

impl SkelRef {
    fn from_stmt(s: &MapStmt) -> Self {
        SkelRef {
            loc: s.loc.clone(),
            construct: s.construct.clone(),
            line: s.span.line,
            col: s.span.col,
            end_line: s.span.end_line,
            end_col: s.span.end_col,
            reqs: s.reqs.clone(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct MappedDiagnostic {
    pub code: String,
    pub severity: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub skel: Option<SkelRef>,
    pub unmapped: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub origin: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CounterexampleStep {
    pub step: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thread: Option<u64>,
    pub function: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub skel: Option<SkelRef>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub statement: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Counterexample {
    pub property: String,
    pub reqs: Vec<String>,
    pub steps: Vec<CounterexampleStep>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_note: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct PropertyFeedback {
    pub id: String,
    pub outcome: String,
    pub detail: String,
    pub reqs: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct VerifyFeedback {
    pub outcome: String,
    pub complete: bool,
    pub properties: Vec<PropertyFeedback>,
    pub counterexamples: Vec<Counterexample>,
    pub diagnostics: Vec<MappedDiagnostic>,
    pub unmapped: usize,
}

pub struct Mapper<'a> {
    program: &'a Program,
    stmts: HashMap<String, &'a MapStmt>,
    json_paths: &'a BTreeMap<String, String>,
    /// Flattened `(module, function, sids-in-order)` indexed by FunctionId.
    funcs: Vec<(String, String, Vec<String>)>,
}

impl<'a> Mapper<'a> {
    pub fn new(program: &'a Program, map: &'a SourceMap) -> Self {
        let stmts = map.stmts.iter().map(|s| (s.loc.clone(), s)).collect();
        let mut funcs = Vec::new();
        for m in &program.modules {
            for f in &m.functions {
                funcs.push((
                    m.name.clone(),
                    f.name.clone(),
                    f.body.iter().map(|s| s.sid.clone()).collect(),
                ));
            }
        }
        Mapper {
            program,
            stmts,
            json_paths: &map.json_paths,
            funcs,
        }
    }

    pub fn lookup_loc(&self, loc: &str) -> Option<SkelRef> {
        // ConcIR `module::function.sid` -> source-map `module::function::sid`.
        let key = match loc.rsplit_once('.') {
            Some((head, sid)) if !head.is_empty() && sid.starts_with('s') => {
                format!("{head}::{sid}")
            }
            _ => loc.to_string(),
        };
        if let Some(s) = self.stmts.get(&key) {
            return Some(SkelRef::from_stmt(s));
        }
        // Function-level location: map to the first statement of that function
        // if present, else leave unmapped.
        None
    }

    fn lookup_path(&self, path: &str) -> Option<SkelRef> {
        let loc = self.json_paths.get(path)?;
        self.stmts.get(loc).map(|s| SkelRef::from_stmt(s))
    }

    fn lookup_origin(&self, function_id: usize, sid_index: Option<usize>) -> Option<SkelRef> {
        let (module, function, sids) = self.funcs.get(function_id)?;
        let sid = sid_index.and_then(|i| sids.get(i))?;
        self.lookup_loc(&format!("{module}::{function}::{sid}"))
    }

    fn fn_name(&self, function_id: usize) -> String {
        self.funcs
            .get(function_id)
            .map(|(m, f, _)| format!("{m}::{f}"))
            .unwrap_or_else(|| format!("function#{function_id}"))
    }

    pub fn map_validation(&self, report: &ValidationReport) -> (Vec<MappedDiagnostic>, usize) {
        let mut out = Vec::new();
        let mut unmapped = 0usize;
        for d in &report.diagnostics {
            let skel = d
                .location
                .as_deref()
                .and_then(|l| self.lookup_loc(l))
                .or_else(|| d.path.as_deref().and_then(|p| self.lookup_path(p)));
            let is_unmapped = skel.is_none();
            if is_unmapped {
                unmapped += 1;
            }
            out.push(MappedDiagnostic {
                code: d.code.to_string(),
                severity: format!("{:?}", d.severity).to_lowercase(),
                message: d.message.clone(),
                skel,
                unmapped: is_unmapped,
                hint: d.fix_hint.clone(),
                origin: Some("concir".into()),
            });
        }
        (out, unmapped)
    }

    pub fn map_verify(
        &self,
        report: &VerificationReport,
        contract_reqs: &BTreeMap<String, Vec<String>>,
        file: &SourceFile,
    ) -> VerifyFeedback {
        let mut unmapped = 0usize;
        let mut diagnostics = Vec::new();
        let mut counterexamples = Vec::new();

        for d in &report.diagnostics {
            let skel = d
                .cir_statements
                .iter()
                .find_map(|r| {
                    let loc = match &r.sid {
                        Some(sid) => format!("{}::{}::{sid}", r.module, r.function),
                        None => format!("{}::{}", r.module, r.function),
                    };
                    self.lookup_loc(&loc)
                });
            let is_unmapped = skel.is_none();
            if is_unmapped {
                unmapped += 1;
            }
            diagnostics.push(MappedDiagnostic {
                code: format!("property:{}", d.property),
                severity: "info".into(),
                message: d.message.clone(),
                skel,
                unmapped: is_unmapped,
                hint: None,
                origin: Some("concir".into()),
            });
            // Counterexample.
            let mut steps = Vec::new();
            for (i, label) in d.counterexample.iter().enumerate() {
                let (thread, skel_ref, statement) = self.map_step(label, file);
                if skel_ref.is_none() {
                    // Unmappable steps are counted below via the total check.
                }
                steps.push(CounterexampleStep {
                    step: i + 1,
                    thread: thread.map(|t| t.0),
                    function: self.fn_name(label.origin.function.0 as usize),
                    skel: skel_ref,
                    statement,
                });
            }
            // Map final instances / doom state for a final note.
            let final_note = render_final(d);
            counterexamples.push(Counterexample {
                property: d.property.clone(),
                reqs: contract_reqs.get(&d.property).cloned().unwrap_or_default(),
                steps,
                final_note,
            });
        }

        for inv in &report.invalid {
            let skel = inv.location.as_deref().and_then(|l| self.lookup_loc(l));
            let is_unmapped = skel.is_none();
            if is_unmapped {
                unmapped += 1;
            }
            diagnostics.push(MappedDiagnostic {
                code: inv.code.clone(),
                severity: "error".into(),
                message: inv.message.clone(),
                skel,
                unmapped: is_unmapped,
                hint: None,
                origin: Some("concir".into()),
            });
        }
        for u in &report.unsupported {
            let skel = u.location.as_deref().and_then(|l| self.lookup_loc(l));
            let is_unmapped = skel.is_none();
            if is_unmapped {
                unmapped += 1;
            }
            diagnostics.push(MappedDiagnostic {
                code: "UNSUPPORTED".into(),
                severity: "error".into(),
                message: format!("{}: {}", u.construct, u.detail),
                skel,
                unmapped: is_unmapped,
                hint: None,
                origin: Some("concir".into()),
            });
        }

        // Count unmapped steps in counterexamples.
        for ce in &counterexamples {
            for st in &ce.steps {
                if st.skel.is_none() {
                    unmapped += 1;
                }
            }
        }

        let properties = report
            .properties
            .iter()
            .map(|p| PropertyFeedback {
                id: p.id.clone(),
                outcome: p.outcome.as_str().to_string(),
                detail: p.detail.clone(),
                reqs: contract_reqs.get(&p.id).cloned().unwrap_or_default(),
            })
            .collect();

        VerifyFeedback {
            outcome: report.outcome.as_str().to_string(),
            complete: report.complete,
            properties,
            counterexamples,
            diagnostics,
            unmapped,
        }
    }

    fn map_step(
        &self,
        label: &StepLabel,
        file: &SourceFile,
    ) -> (Option<concir::sem::ids::ThreadId>, Option<SkelRef>, Option<String>) {
        let skel = self.lookup_origin(label.origin.function.0 as usize, label.origin.sid);
        let statement = skel
            .as_ref()
            .map(|s| file.line(s.line).trim().to_string());
        (label.thread, skel, statement)
    }
}

fn render_final(d: &concir::explore::DiagnosticRecord) -> Option<String> {
    let doom = &d.doom_state;
    if doom.threads.is_empty() {
        return None;
    }
    let mut parts = Vec::new();
    for t in &doom.threads {
        let holds = if t.holds.is_empty() {
            String::new()
        } else {
            format!(" holds [{}]", t.holds.join(", "))
        };
        let wait = t
            .waiting_on
            .as_ref()
            .map(|w| format!(" waits {} {}", w.kind, w.resource.clone().unwrap_or_default()))
            .unwrap_or_default();
        parts.push(format!("T{}{}{}", t.thread, holds, wait));
    }
    Some(parts.join("; "))
}

/// Render a counterexample as the interleaved table from §5.5.
pub fn render_counterexample(ce: &Counterexample) -> String {
    let reqs = if ce.reqs.is_empty() {
        String::new()
    } else {
        format!(", requirements {}", ce.reqs.join(" "))
    };
    let mut out = format!(
        "counterexample (property {}{}):\n",
        ce.property, reqs
    );
    out.push_str("  step thread fn                 line  statement\n");
    for st in &ce.steps {
        let thread = st
            .thread
            .map(|t| format!("T{t}"))
            .unwrap_or_else(|| "-".to_string());
        let line = st
            .skel
            .as_ref()
            .map(|s| s.line.to_string())
            .unwrap_or_else(|| "?".to_string());
        let statement = st.statement.clone().unwrap_or_default();
        out.push_str(&format!(
            "  {:<4} {:<6} {:<18} {:<5} {}\n",
            st.step, thread, st.function, line, statement
        ));
    }
    if let Some(note) = &ce.final_note {
        out.push_str(&format!("final: {note}\n"));
    }
    out
}

/// Extract `property id -> requirement ids` from a contract document.
pub fn contract_property_reqs(contract: &serde_json::Value) -> BTreeMap<String, Vec<String>> {
    let mut out = BTreeMap::new();
    for key in ["properties", "preserved"] {
        if let Some(arr) = contract.get(key).and_then(|v| v.as_array()) {
            for p in arr {
                let id = match p.get("id").and_then(|v| v.as_str()) {
                    Some(id) => id.to_string(),
                    None => match p.get("description").and_then(|v| v.as_str()) {
                        Some(d) => format!("preserved: {d}"),
                        None => continue,
                    },
                };
                let reqs: Vec<String> = p
                    .get("req")
                    .and_then(|v| v.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_str().map(String::from))
                            .collect()
                    })
                    .unwrap_or_default();
                out.insert(id, reqs);
            }
        }
    }
    out
}

