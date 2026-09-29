//! Two finite iterations of gold.skel's sequential helper call loop.
//! Return values count completed calls without introducing shared state.
fn helper() -> u32 {
    let mut completed = 0;
    completed += 1;
    completed
}

fn main() {
    let mut calls = 0;
    for _ in 0..2 {
        calls += helper();
    }
    println!("DONE calls={}", calls);
}
