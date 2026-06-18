//! Radix-trie router backend for gunbullet.
//!
//! This is the compiled drop-in replacement for the pure-Python `PyRouter`
//! (`gunbullet/_router_py.py`). It exposes the same surface to Python:
//!
//! * `add(pattern, route_id)` registers a route under an integer id.
//! * `match(path)` returns a list of `(params, route_id)` candidates in
//!   priority order -- static (exact) routes first, then dynamic routes in
//!   registration order -- or an empty list when the path matches nothing.
//!   The caller picks the first candidate whose handler allows the method, so
//!   `len(candidates)` still encodes the 405-vs-404 distinction.
//!
//! Unlike a linear regex scan, matching is a single trie walk: O(path length),
//! independent of how many routes are registered.
//!
//! Supported pattern shape: `<name>` parameters occupy a whole `/`-delimited
//! segment (e.g. `/org/<org>/user/<user_id>`), which covers all of gunbullet's
//! routing. The pure-Python fallback additionally accepts intra-segment
//! parameters (via regex); that shape is not used by the framework.

use pyo3::prelude::*;
use std::collections::HashMap;

/// One node in the dynamic-route trie.
///
/// A param edge carries no name (it matches any non-empty segment); the
/// parameter *names* live on the terminal, paired with their route id, because
/// two routes can share a structure but name their slots differently
/// (`/users/<id>` vs `/users/<name>`).
#[derive(Default)]
struct Node {
    static_children: HashMap<String, Node>,
    param_child: Option<Box<Node>>,
    /// (route_id, param_names_in_order) for routes terminating at this node.
    terminals: Vec<(usize, Vec<String>)>,
}

fn is_param(seg: &str) -> bool {
    seg.len() >= 3 && seg.starts_with('<') && seg.ends_with('>')
}

fn walk(node: &Node, segs: &[&str], idx: usize, caps: &mut Vec<String>, out: &mut Vec<(usize, HashMap<String, String>)>) {
    if idx == segs.len() {
        for (rid, names) in &node.terminals {
            let mut params = HashMap::with_capacity(names.len());
            for (name, value) in names.iter().zip(caps.iter()) {
                params.insert(name.clone(), value.clone());
            }
            out.push((*rid, params));
        }
        return;
    }
    let seg = segs[idx];
    if let Some(child) = node.static_children.get(seg) {
        walk(child, segs, idx + 1, caps, out);
    }
    // A `[^/]+` param never matches an empty segment (mirrors the Python regex).
    if !seg.is_empty() {
        if let Some(child) = &node.param_child {
            caps.push(seg.to_string());
            walk(child, segs, idx + 1, caps, out);
            caps.pop();
        }
    }
}

#[pyclass]
struct Router {
    /// Exact-path routes, keyed by the full pattern; values preserve
    /// registration order (matches the Python `_static` map).
    static_routes: HashMap<String, Vec<usize>>,
    root: Node,
}

#[pymethods]
impl Router {
    #[new]
    fn new() -> Self {
        Router {
            static_routes: HashMap::new(),
            root: Node::default(),
        }
    }

    fn add(&mut self, pattern: &str, route_id: usize) {
        if !pattern.contains('<') {
            self.static_routes
                .entry(pattern.to_string())
                .or_default()
                .push(route_id);
            return;
        }
        let mut node = &mut self.root;
        let mut names: Vec<String> = Vec::new();
        for seg in pattern.split('/') {
            if is_param(seg) {
                names.push(seg[1..seg.len() - 1].to_string());
                node = node.param_child.get_or_insert_with(|| Box::new(Node::default()));
            } else {
                node = node.static_children.entry(seg.to_string()).or_default();
            }
        }
        node.terminals.push((route_id, names));
    }

    #[pyo3(name = "match")]
    fn match_(&self, path: &str) -> Vec<(HashMap<String, String>, usize)> {
        let mut result: Vec<(HashMap<String, String>, usize)> = Vec::new();

        // Static (exact) routes win, in registration order.
        if let Some(ids) = self.static_routes.get(path) {
            for id in ids {
                result.push((HashMap::new(), *id));
            }
        }

        // Dynamic routes: one trie walk, then order candidates by route_id so
        // they appear in registration order (as the Python linear scan did).
        let segs: Vec<&str> = path.split('/').collect();
        let mut dynamic: Vec<(usize, HashMap<String, String>)> = Vec::new();
        let mut caps: Vec<String> = Vec::new();
        walk(&self.root, &segs, 0, &mut caps, &mut dynamic);
        dynamic.sort_by_key(|(rid, _)| *rid);
        for (rid, params) in dynamic {
            result.push((params, rid));
        }

        result
    }
}

#[pymodule]
fn _gunbullet_router(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Router>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    //! `Router::add` / `Router::match_` are plain Rust (no `Python` token in
    //! their signatures), so the routing logic is exercised here with no
    //! interpreter -- `cargo test` proves correctness even where the host
    //! linker cannot produce a loadable extension module.
    use super::*;

    fn ids(m: &[(HashMap<String, String>, usize)]) -> Vec<usize> {
        m.iter().map(|(_, id)| *id).collect()
    }

    #[test]
    fn static_exact_match() {
        let mut r = Router::new();
        r.add("/", 0);
        r.add("/health", 1);
        assert_eq!(ids(&r.match_("/")), vec![0]);
        assert_eq!(ids(&r.match_("/health")), vec![1]);
        assert!(r.match_("/missing").is_empty());
    }

    #[test]
    fn dynamic_single_param() {
        let mut r = Router::new();
        r.add("/age/<age>", 0);
        let m = r.match_("/age/37");
        assert_eq!(m.len(), 1);
        assert_eq!(m[0].0.get("age").map(String::as_str), Some("37"));
        assert_eq!(m[0].1, 0);
        // `[^/]+` never matches an empty trailing segment.
        assert!(r.match_("/age/").is_empty());
    }

    #[test]
    fn dynamic_multi_param_order() {
        let mut r = Router::new();
        r.add("/org/<org>/user/<user_id>", 0);
        let m = r.match_("/org/acme/user/42");
        assert_eq!(m.len(), 1);
        assert_eq!(m[0].0.get("org").map(String::as_str), Some("acme"));
        assert_eq!(m[0].0.get("user_id").map(String::as_str), Some("42"));
    }

    #[test]
    fn static_wins_over_dynamic_and_keeps_registration_order() {
        let mut r = Router::new();
        r.add("/users/<id>", 0); // dynamic registered first
        r.add("/users/me", 1); // static
        // Static is emitted first (priority), dynamic second.
        assert_eq!(ids(&r.match_("/users/me")), vec![1, 0]);
    }

    #[test]
    fn multiple_handlers_same_pattern_and_distinct_param_names() {
        let mut r = Router::new();
        r.add("/age/<age>", 0); // e.g. GET
        r.add("/age/<years>", 1); // same shape, different slot name, e.g. POST
        let m = r.match_("/age/5");
        // Both candidates, in registration order.
        assert_eq!(ids(&m), vec![0, 1]);
        assert_eq!(m[0].0.get("age").map(String::as_str), Some("5"));
        assert_eq!(m[1].0.get("years").map(String::as_str), Some("5"));
    }
}
