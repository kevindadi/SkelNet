//! `skelnet codegen`: deterministic Rust skeleton from ConcIR codegen, with a
//! `// skel:L<line> @R..` comment at every generated statement (ablation /
//! fallback path).

use concir::ast::Program;

use crate::lower::SourceMap;

pub struct CodegenOutput {
    pub main_rs: String,
    pub cargo_toml: String,
    pub trace_rs: String,
    pub holes: serde_json::Value,
}

pub fn codegen(program: &Program, map: &SourceMap) -> Result<CodegenOutput, String> {
    let sem = concir::sem::program::lower(program).map_err(|e| format!("{e:?}"))?;
    let generated = concir::codegen::generate(&sem).map_err(|e| e.to_string())?;

    // The codegen emits `// @cir <sid>` in the same (module, function, body)
    // order as our source map, so we can annotate by walking both in lockstep.
    let mut annotated = String::new();
    let mut idx = 0usize;
    for line in generated.main_rs.lines() {
        let mut out = line.to_string();
        if let Some(pos) = line.find("// @cir ") {
            let sid = line[pos + "// @cir ".len()..].trim();
            let entry = if idx < map.stmts.len() && sid_matches(&map.stmts[idx].loc, sid) {
                let e = &map.stmts[idx];
                idx += 1;
                Some(e)
            } else {
                map.stmts
                    .iter()
                    .position(|e| sid_matches(&e.loc, sid))
                    .map(|j| {
                        let e = &map.stmts[j];
                        idx = j + 1;
                        e
                    })
            };
            if let Some(e) = entry {
                let reqs = if e.reqs.is_empty() {
                    String::new()
                } else {
                    format!(" {}", e.reqs.iter().map(|r| format!("@{r}")).collect::<Vec<_>>().join(" "))
                };
                out.push_str(&format!(" // skel:L{}{reqs}", e.span.line));
            }
        }
        annotated.push_str(&out);
        annotated.push('\n');
    }

    let holes = serde_json::to_value(&generated.map.holes).unwrap_or_default();
    Ok(CodegenOutput {
        main_rs: annotated,
        cargo_toml: generated.cargo_toml,
        trace_rs: generated.trace_rs,
        holes,
    })
}

fn sid_matches(loc: &str, sid: &str) -> bool {
    loc.rsplit("::").next() == Some(sid)
}
