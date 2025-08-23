"""
STEP/IGES/Other CAD to three-cad-viewer JSON converter.

This is a thin wrapper around the excellent ocp-tessellate package, using either
build123d or cadquery to import CAD files into OpenCascade shapes and then
exporting the three-cad-viewer data structure (as used by 3d-sources/test.json).

Usage:
    python -m three_d_resume.step_to_json --in model.step --out 3d-sources/model.json \
        [--name MyModel] [--deflection 0.1] [--angle 12] [--color #cccccc]

Alternatively once installed:
    step-to-json --in model.step --out out.json

Notes:
- This tool requires optional dependencies that are NOT installed by default:
  - ocp-tessellate (https://github.com/bernhard-42/ocp-tessellate)
  - and either build123d or cadquery to import the CAD file
- If these are missing, the tool will print instructions and exit.
- The output is strict JSON compatible with assets/js/app.js fetchShapes() parser.

"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from typing import Any, List, Optional, Tuple


def _try_import_builders():
    """Try to import a CAD importer. Return a tuple (backend, importer_fn).

    backend is one of: 'build123d', 'cadquery'
    importer_fn(path) -> list of shapes or a single shape
    """
    # Try build123d first (modern)
    try:
        import build123d as b3d  # type: ignore
        from build123d import importers as b3d_importers  # type: ignore

        def _import_step_b3d(path: str):
            # build123d returns a Part or list depending on file
            return b3d_importers.import_step(path)

        return ("build123d", _import_step_b3d)
    except Exception:
        pass

    # Try cadquery
    try:
        import cadquery as cq  # type: ignore

        def _import_step_cq(path: str):
            # cadquery may offer importers at different places between versions
            try:
                from cadquery import importers as cq_importers  # type: ignore

                return cq_importers.importStep(path)
            except Exception:
                # Fallback via Shape
                return cq.Shape.importStep(path)

        return ("cadquery", _import_step_cq)
    except Exception:
        pass

    return (None, None)


def _to_sequence(shapes_obj) -> List[Any]:
    """Normalize shapes into a list."""
    if shapes_obj is None:
        return []
    if isinstance(shapes_obj, (list, tuple)):
        return list(shapes_obj)
    return [shapes_obj]


def _normalize_cad_objects(shapes: List[Any]) -> List[Any]:
    """Best-effort normalization for cadquery/build123d containers.

    - If given a cadquery Workplane, expand to its .objects
    - If given a cadquery Compound, expand to its Solids()
    - Otherwise, return as-is
    """
    out: List[Any] = []
    for s in shapes:
        try:
            # cadquery Workplane has .objects list of shapes
            objs = getattr(s, "objects", None)
            if isinstance(objs, (list, tuple)) and objs:
                out.extend(list(objs))
                continue
            # cadquery Compound has .Solids()/.solids()
            if hasattr(s, "Solids") and callable(getattr(s, "Solids")):
                sols = s.Solids()
                if isinstance(sols, (list, tuple)) and sols:
                    out.extend(list(sols))
                    continue
            if hasattr(s, "solids") and callable(getattr(s, "solids")):
                sols = s.solids()
                try:
                    sols = list(sols)
                except Exception:
                    pass
                if isinstance(sols, (list, tuple)) and sols:
                    out.extend(list(sols))
                    continue
        except Exception:
            pass
        out.append(s)
    return out


def _try_import_ocp():
    """Try to import OCCT exploration utilities from OCP. Returns a tuple or None.

    On success returns (TopoDS_Shape, TopoDS_Compound, TopExp_Explorer, TopAbs)
    """
    try:
        from OCP.TopoDS import TopoDS_Shape, TopoDS_Compound  # type: ignore
        from OCP.TopExp import TopExp_Explorer  # type: ignore
        from OCP.TopAbs import TopAbs  # type: ignore

        return (TopoDS_Shape, TopoDS_Compound, TopExp_Explorer, TopAbs)
    except Exception:
        return None


def _explode_compound_to_supported(shape: Any) -> List[Any]:
    """Explode a compound into supported sub-shapes (Solids -> Shells -> Faces).

    Accepts build123d/cadquery shapes (with .wrapped) or raw TopoDS_Shape. If not a
    compound or if OCP is not available, returns [shape] unchanged.
    This function is recursive to handle nested compounds/assemblies.
    """
    ocp = _try_import_ocp()
    if not ocp:
        return [shape]
    TopoDS_Shape, TopoDS_Compound, TopExp_Explorer, TopAbs = ocp

    topo = getattr(shape, "wrapped", shape)

    def _is_compound(t) -> bool:
        # robust detection even if ShapeType is missing
        try:
            return isinstance(t, TopoDS_Compound) or (
                hasattr(t, "ShapeType") and t.ShapeType() == TopAbs.TopAbs_COMPOUND
            )
        except Exception:
            # very last resort: check class name string (helps with proxies)
            return (
                isinstance(t, TopoDS_Compound)
                or (type(t).__name__ == "TopoDS_Compound")
            )

    def _collect_from(t, kind):
        out = []
        exp = None
        # Try multiple constructor signatures and Init pattern across OCP variants
        try:
            exp = TopExp_Explorer(t, kind)
        except Exception:
            try:
                exp = TopExp_Explorer(t, kind, TopAbs.TopAbs_SHAPE)
            except Exception:
                try:
                    exp = TopExp_Explorer()
                    try:
                        exp.Init(t, kind)
                    except Exception:
                        exp = None
                except Exception:
                    exp = None
        if exp is None:
            return []
        try:
            while exp.More():
                out.append(exp.Current())
                exp.Next()
        except Exception:
            return []
        return out

    try:

        # Try to collect solids even if compound detection fails
        solids = _collect_from(topo, TopAbs.TopAbs_SOLID)
        if solids:
            return solids

        # Some STEP assemblies may use compsolid; explode to solids
        try:
            compsolids = _collect_from(topo, TopAbs.TopAbs_COMPSOLID)
        except Exception:
            compsolids = []
        if compsolids:
            solids_nested: List[Any] = []
            for cs in compsolids:
                solids_nested.extend(_collect_from(cs, TopAbs.TopAbs_SOLID))
            if solids_nested:
                return solids_nested

        # Next try shells, then faces
        shells = _collect_from(topo, TopAbs.TopAbs_SHELL)
        if shells:
            return shells
        faces = _collect_from(topo, TopAbs.TopAbs_FACE)
        if faces:
            return faces

        # Finally, if there are nested compounds, recurse into them
        compounds = _collect_from(topo, TopAbs.TopAbs_COMPOUND)
        if compounds:
            parts: List[Any] = []
            for c in compounds:
                parts.extend(_explode_compound_to_supported(c))
            if parts:
                return parts

        # Fallback: return original if nothing found
        return [shape]
    except Exception:
        return [shape]


def _flatten_shapes(shapes: List[Any]) -> List[Any]:
    """Flatten a list of shapes, exploding compounds into supported primitives."""
    flat: List[Any] = []
    for s in shapes:
        parts = _explode_compound_to_supported(s)
        flat.extend(parts)
    return flat


def _looks_like_compound(obj: Any) -> bool:
    """Best-effort detector for compound shapes even if OCP can't be imported here."""
    # Try OCP-based detection first
    ocp = _try_import_ocp()
    topo = getattr(obj, "wrapped", obj)
    if ocp:
        TopoDS_Shape, TopoDS_Compound, _TopExp_Explorer, TopAbs = ocp
        try:
            if isinstance(topo, TopoDS_Compound):
                return True
            if hasattr(topo, "ShapeType") and topo.ShapeType() == TopAbs.TopAbs_COMPOUND:
                return True
        except Exception:
            pass
    # Fallback string name
    try:
        return type(topo).__name__ == "TopoDS_Compound"
    except Exception:
        return False


def _parse_js_object_literal(text: str) -> Any:
    """Very small helper to turn a JS-like object literal into JSON, then parse.

    This tries to be robust against the format written by ocp_tessellate's
    export_three_cad_viewer_js, which typically emits something like:

        var NAME = { version: 3, parts: [ ... ], };

    We:
      - strip any leading `var NAME =` or `const NAME =` or `export const NAME =`
      - remove trailing semicolon
      - quote bare keys
      - remove trailing commas
    Then json.loads() the result.
    """
    src = text.strip()
    # Remove leading assignment patterns
    src = re.sub(r"^(?:export\s+)?(?:const|var|let)\s+[a-zA-Z_$][\w$]*\s*=\s*", "", src)
    # Remove trailing semicolon
    src = re.sub(r";\s*$", "", src)

    # Find first object start and last end to cut unrelated code
    start = src.find("{")
    end = src.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Could not locate object literal in JS text")
    src = src[start : end + 1]

    # Quote bare keys: from key: to "key":
    # Note: keep it conservative to avoid touching strings
    src = re.sub(r"(?m)(^|[,{\s])([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', src)
    # Remove trailing commas in objects/arrays
    src = re.sub(r",\s*([}\]])", r"\1", src)

    return json.loads(src)


def convert_step_to_json(
    input_path: str,
    output_path: str,
    *,
    model_name: Optional[str] = None,
    color: Optional[str] = None,
    deflection: float = 0.1,
    angle: float = 12.0,
) -> dict:
    """Convert a STEP (or other supported) file to three-cad-viewer JSON.

    Returns the JSON object (also written to output_path).
    """
    # Import a builder backend
    backend, importer = _try_import_builders()
    if not importer:
        raise RuntimeError(
            "No CAD importer found. Please install either 'build123d' or 'cadquery'."
        )

    try:
        from ocp_tessellate.convert import export_three_cad_viewer_js  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Missing dependency 'ocp-tessellate'. Install with: pip install ocp-tessellate"
        ) from e

    shapes_obj = importer(input_path)
    original = _to_sequence(shapes_obj)
    # First, normalize potential cadquery/build123d containers (Workplanes, Compounds)
    shapes = _normalize_cad_objects(list(original))
    # Iteratively flatten compounds to supported primitives to avoid passing
    # TopoDS_Compound into the exporter (which raises Unknown type errors)
    for _ in range(5):  # depth guard
        if any(_looks_like_compound(s) for s in shapes):
            shapes = _flatten_shapes(shapes)
        else:
            break
    if not shapes:
        raise RuntimeError(f"No shapes found in input file: {input_path}")

    # Export as JS (ocp-tessellate currently provides JS; we'll parse to JSON)
    base = model_name or os.path.splitext(os.path.basename(input_path))[0]
    with tempfile.TemporaryDirectory() as td:
        js_path = os.path.join(td, f"{base}.js")
        # Call exporter; it accepts multiple ocp shapes as positional args
        names = [f"{base}_{i}" for i in range(len(shapes))]
        try:
            try:
                export_three_cad_viewer_js(
                    base,
                    *shapes,
                    names=names,
                    filename=js_path,
                    # pass through tessellation quality if supported
                    angular_tolerance=angle,
                    linear_tolerance=deflection,
                )
            except TypeError:
                # Fallback for older ocp-tessellate versions without tolerance args
                export_three_cad_viewer_js(
                    base,
                    *shapes,
                    names=names,
                    filename=js_path,
                )
        except Exception as e:
            # Last-ditch attempt: if compounds slipped through, explode and retry once
            msg = str(e)
            if "TopoDS_Compound" in msg or "Compound" in msg:
                retry_shapes: List[Any] = []
                for s in shapes:
                    retry_shapes.extend(_explode_compound_to_supported(s))
                if retry_shapes:
                    shapes = retry_shapes
                    names = [f"{base}_{i}" for i in range(len(shapes))]
                    try:
                        try:
                            export_three_cad_viewer_js(
                                base,
                                *shapes,
                                names=names,
                                filename=js_path,
                                angular_tolerance=angle,
                                linear_tolerance=deflection,
                            )
                        except TypeError:
                            export_three_cad_viewer_js(
                                base,
                                *shapes,
                                names=names,
                                filename=js_path,
                            )
                    except Exception:
                        raise
                else:
                    raise
            else:
                raise

        with open(js_path, "r", encoding="utf-8") as f:
            js_text = f.read()

    data = _parse_js_object_literal(js_text)

    # Optionally override color if requested
    if color:
        try:
            for p in data.get("parts", []):
                if isinstance(p, dict):
                    if "color" in p:
                        p["color"] = color
        except Exception:
            pass

    # Ensure strict JSON is written
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    return data


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Convert STEP to three-cad-viewer JSON")
    p.add_argument("--in", dest="input", required=True, help="Path to input STEP/IGES file")
    p.add_argument("--out", dest="output", required=True, help="Path to output JSON file")
    p.add_argument("--name", dest="name", default=None, help="Model name (defaults to file stem)")
    p.add_argument("--color", dest="color", default=None, help="Hex color override, e.g. #ff0000")
    p.add_argument("--deflection", dest="deflection", type=float, default=0.1, help="Linear deflection (tessellation)")
    p.add_argument("--angle", dest="angle", type=float, default=12.0, help="Angular tolerance in degrees")

    args = p.parse_args(argv)

    try:
        convert_step_to_json(
            args.input,
            args.output,
            model_name=args.name,
            color=args.color,
            deflection=args.deflection,
            angle=args.angle,
        )
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.stderr.write(
            "Hint: pip install ocp-tessellate and either build123d or cadquery to enable conversion.\n"
        )
        return 2

    print(f"Wrote JSON to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
