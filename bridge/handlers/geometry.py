"""Handlers for geometry attribute endpoints: get_attribs, attrib_info, attrib_stats, attrib_values."""

import math
from collections import Counter

import hou
from bridge.main_thread import _run_on_main_thread


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_geo(path):
    """Resolve node path to a hou.Geometry, raising on failure."""
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")
    geo = node.geometry()
    if geo is None:
        raise ValueError(f"No geometry on node: {path}")
    return geo


def _class_config(geo, attrib_class):
    """Return (attribs_fn, float_fn, int_fn, string_fn, elem_count) for a class."""
    configs = {
        "point":  (geo.pointAttribs,  geo.pointFloatAttribValues,  geo.pointIntAttribValues,  geo.pointStringAttribValues,  len(geo.points())),
        "prim":   (geo.primAttribs,   geo.primFloatAttribValues,   geo.primIntAttribValues,   geo.primStringAttribValues,   len(geo.prims())),
        "vertex": (geo.vertexAttribs, geo.vertexFloatAttribValues, geo.vertexIntAttribValues, geo.vertexStringAttribValues, geo.intrinsicValue("vertexcount")),
        "detail": (geo.globalAttribs, None, None, None, 1),
    }
    cfg = configs.get(attrib_class)
    if cfg is None:
        raise ValueError(f"Invalid attrib_class: {attrib_class}. Use: point, prim, vertex, detail")
    return cfg


def _scalar_stats(vals):
    """Compute min/max/mean/stddev for a flat sequence of numbers."""
    n = len(vals)
    mn = min(vals)
    mx = max(vals)
    s = sum(vals)
    mean = s / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return mn, mx, mean, math.sqrt(var)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def handle_get_attribs(body):
    """Get geometry attribute metadata (name, type, size) for one class."""
    path = body.get("path", "")
    attrib_class = body.get("attrib_class", "point")
    if not path:
        return {"success": False, "error": "No 'path' provided"}, 400

    def task():
        geo = _get_geo(path)
        attribs_fn = _class_config(geo, attrib_class)[0]
        return [
            {"name": a.name(), "type": a.dataType().name(), "size": a.size()}
            for a in attribs_fn()
        ]

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_attrib_info(body):
    """Full geometry overview — all attrib names/types across all classes."""
    path = body.get("path", "")
    if not path:
        return {"success": False, "error": "No 'path' provided"}, 400

    def task():
        geo = _get_geo(path)

        def attrib_list(attribs):
            return [{"name": a.name(), "type": a.dataType().name(), "size": a.size()} for a in attribs]

        return {
            "point_count": len(geo.points()),
            "prim_count": len(geo.prims()),
            "vertex_count": geo.intrinsicValue("vertexcount"),
            "point_attribs": attrib_list(geo.pointAttribs()),
            "prim_attribs": attrib_list(geo.primAttribs()),
            "vertex_attribs": attrib_list(geo.vertexAttribs()),
            "detail_attribs": attrib_list(geo.globalAttribs()),
        }

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_attrib_stats(body):
    """Compute stats (min/max/mean/stddev/samples) for specific attributes."""
    path = body.get("path", "")
    attrib_class = body.get("attrib_class", "point")
    attrib_names = body.get("attribs", None)
    num_samples = min(body.get("samples", 5), 50)
    if not path:
        return {"success": False, "error": "No 'path' provided"}, 400

    def task():
        geo = _get_geo(path)
        attribs_fn, float_fn, int_fn, string_fn, elem_count = _class_config(geo, attrib_class)

        attribs = attribs_fn()
        if attrib_names:
            name_set = set(attrib_names)
            attribs = [a for a in attribs if a.name() in name_set]

        # Evenly-spaced sample indices
        if elem_count <= num_samples:
            sample_indices = list(range(elem_count))
        else:
            step = (elem_count - 1) / max(num_samples - 1, 1)
            sample_indices = [int(round(i * step)) for i in range(num_samples)]

        result = {}
        for attrib in attribs:
            name = attrib.name()
            dtype = attrib.dataType().name()
            size = attrib.size()
            info = {"type": dtype, "size": size, "count": elem_count}

            if attrib_class == "detail":
                try:
                    info["value"] = attrib.defaultValue() if elem_count == 0 else geo.attribValue(name)
                except Exception:
                    info["value"] = None
                result[name] = info
                continue

            if dtype in ("Float", "Int"):
                vals = float_fn(name) if dtype == "Float" else int_fn(name)
                if not vals:
                    result[name] = info
                    continue

                if size == 1:
                    mn, mx, mean, stddev = _scalar_stats(vals)
                    info["min"] = mn
                    info["max"] = mx
                    info["mean"] = mean
                    info["stddev"] = stddev
                    info["samples"] = {
                        "indices": sample_indices,
                        "values": [vals[i] for i in sample_indices],
                    }
                else:
                    mins, maxs, means, stddevs = [], [], [], []
                    for c in range(size):
                        comp = vals[c::size]
                        mn, mx, mean, sd = _scalar_stats(comp)
                        mins.append(mn)
                        maxs.append(mx)
                        means.append(mean)
                        stddevs.append(sd)
                    info["min"] = mins
                    info["max"] = maxs
                    info["mean"] = means
                    info["stddev"] = stddevs
                    info["samples"] = {
                        "indices": sample_indices,
                        "values": [list(vals[i * size:(i + 1) * size]) for i in sample_indices],
                    }
                    # Magnitude stats for vectors
                    n = elem_count
                    mag_min = float("inf")
                    mag_max = 0.0
                    mag_sum = 0.0
                    mag_sq_sum = 0.0
                    for i in range(n):
                        sq = sum(vals[i * size + c] ** 2 for c in range(size))
                        mag = math.sqrt(sq)
                        if mag < mag_min:
                            mag_min = mag
                        if mag > mag_max:
                            mag_max = mag
                        mag_sum += mag
                        mag_sq_sum += mag * mag
                    mag_mean = mag_sum / n
                    mag_var = mag_sq_sum / n - mag_mean ** 2
                    info["magnitude"] = {
                        "min": mag_min,
                        "max": mag_max,
                        "mean": mag_mean,
                        "stddev": math.sqrt(max(mag_var, 0)),
                    }

            elif dtype in ("String",):
                vals = string_fn(name)
                counts = Counter(vals)
                info["unique_count"] = len(counts)
                info["top_values"] = dict(counts.most_common(50))
                info["samples"] = {
                    "indices": sample_indices,
                    "values": [vals[i] for i in sample_indices],
                }

            result[name] = info
        return result

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_attrib_values(body):
    """Read sampled attribute values with flexible pagination."""
    path = body.get("path", "")
    attrib_class = body.get("attrib_class", "point")
    attrib_names = body.get("attribs", None)
    start = body.get("start", 0)
    count = min(body.get("count", 20), 5000)
    stride = max(body.get("stride", 1), 1)
    reverse = body.get("reverse", False)
    if not path:
        return {"success": False, "error": "No 'path' provided"}, 400

    def task():
        geo = _get_geo(path)
        attribs_fn, float_fn, int_fn, string_fn, total = _class_config(geo, attrib_class)

        attribs = attribs_fn()
        if attrib_names:
            name_set = set(attrib_names)
            attribs = [a for a in attribs if a.name() in name_set]

        # Compute indices
        if reverse:
            indices = list(range(total - 1 - start, -1, -stride))[:count]
        else:
            indices = list(range(start, total, stride))[:count]

        if attrib_class == "detail":
            attrib_data = {}
            for attrib in attribs:
                try:
                    attrib_data[attrib.name()] = {
                        "type": attrib.dataType().name(),
                        "size": attrib.size(),
                        "values": [geo.attribValue(attrib.name())],
                    }
                except Exception:
                    attrib_data[attrib.name()] = {"type": attrib.dataType().name(), "size": attrib.size(), "values": []}
            return {"total_count": 1, "sampled_count": 1, "indices": [0], "attribs": attrib_data}

        attrib_data = {}
        for attrib in attribs:
            name = attrib.name()
            dtype = attrib.dataType().name()
            size = attrib.size()

            if dtype == "Float":
                vals = float_fn(name)
            elif dtype == "Int":
                vals = int_fn(name)
            elif dtype == "String":
                vals = string_fn(name)
            else:
                continue

            if dtype == "String" or size == 1:
                sampled = [vals[i] for i in indices]
            else:
                sampled = [list(vals[i * size:(i + 1) * size]) for i in indices]

            attrib_data[name] = {"type": dtype, "size": size, "values": sampled}

        return {
            "total_count": total,
            "sampled_count": len(indices),
            "indices": indices,
            "attribs": attrib_data,
        }

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500
