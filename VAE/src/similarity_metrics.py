from __future__ import annotations

import math
from collections import Counter
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


EPS = 1e-12


def finite_values(values: Iterable[object]) -> List[float]:
    result: List[float] = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def summary(values: Iterable[object]) -> Dict[str, float]:
    clean = finite_values(values)
    if not clean:
        return {"count": 0.0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    mean = sum(clean) / len(clean)
    variance = sum((value - mean) ** 2 for value in clean) / len(clean)
    return {
        "count": float(len(clean)),
        "mean": mean,
        "std": math.sqrt(variance),
        "min": min(clean),
        "max": max(clean),
    }


def relative_error(generated: float, reference: float) -> float:
    if abs(reference) > EPS:
        return abs(generated - reference) / abs(reference)
    return abs(generated - reference)


def bounded(value: float, upper: float = 1.0) -> float:
    if not math.isfinite(value):
        return upper
    return max(0.0, min(upper, float(value)))


def counter_from_values(values: Iterable[object]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for value in values:
        if value in (None, ""):
            continue
        counts[str(value)] += 1
    return dict(sorted(counts.items()))


def normalize_counts(counts: Mapping[str, float], keys: Sequence[str] | None = None) -> Dict[str, float]:
    ordered_keys = list(keys) if keys is not None else sorted(str(key) for key in counts)
    total = sum(float(counts.get(key, 0.0)) for key in ordered_keys)
    if total <= EPS:
        return {str(key): 0.0 for key in ordered_keys}
    return {str(key): float(counts.get(key, 0.0)) / total for key in ordered_keys}


def js_divergence(reference: Mapping[str, float], generated: Mapping[str, float]) -> float:
    keys = sorted(set(str(key) for key in reference) | set(str(key) for key in generated))
    if not keys:
        return 0.0
    ref_total = sum(float(reference.get(key, 0.0)) for key in keys)
    gen_total = sum(float(generated.get(key, 0.0)) for key in keys)
    if ref_total <= EPS and gen_total <= EPS:
        return 0.0
    if ref_total <= EPS or gen_total <= EPS:
        return 1.0
    p = [float(reference.get(key, 0.0)) / ref_total for key in keys]
    q = [float(generated.get(key, 0.0)) / gen_total for key in keys]
    m = [(left + right) / 2.0 for left, right in zip(p, q)]

    def kl(left: Sequence[float], right: Sequence[float]) -> float:
        total = 0.0
        for l_value, r_value in zip(left, right):
            if l_value > EPS and r_value > EPS:
                total += l_value * math.log(l_value / r_value, 2)
        return total

    return bounded(0.5 * kl(p, m) + 0.5 * kl(q, m))


def distribution_l1(reference: Mapping[str, float], generated: Mapping[str, float]) -> float:
    keys = sorted(set(str(key) for key in reference) | set(str(key) for key in generated))
    if not keys:
        return 0.0
    p = normalize_counts(reference, keys)
    q = normalize_counts(generated, keys)
    return bounded(0.5 * sum(abs(p[key] - q[key]) for key in keys))


def counter_cosine(reference: Mapping[str, float], generated: Mapping[str, float]) -> float:
    keys = sorted(set(str(key) for key in reference) | set(str(key) for key in generated))
    if not keys:
        return 1.0
    dot = sum(float(reference.get(key, 0.0)) * float(generated.get(key, 0.0)) for key in keys)
    ref_norm = math.sqrt(sum(float(reference.get(key, 0.0)) ** 2 for key in keys))
    gen_norm = math.sqrt(sum(float(generated.get(key, 0.0)) ** 2 for key in keys))
    if ref_norm <= EPS and gen_norm <= EPS:
        return 1.0
    if ref_norm <= EPS or gen_norm <= EPS:
        return 0.0
    return dot / (ref_norm * gen_norm)


def bin_numeric_values(values: Iterable[object], edges: Sequence[float], labels: Sequence[str]) -> Dict[str, int]:
    if len(edges) < 2:
        raise ValueError("edges must contain at least two values")
    if len(labels) != len(edges) - 1:
        raise ValueError("labels length must be len(edges) - 1")
    counts: Counter[str] = Counter({label: 0 for label in labels})
    for raw in finite_values(values):
        value = float(raw)
        placed = False
        for index, label in enumerate(labels):
            low = float(edges[index])
            high = float(edges[index + 1])
            if index == len(labels) - 1:
                if low <= value <= high or math.isinf(high):
                    counts[label] += 1
                    placed = True
                    break
            elif low <= value < high:
                counts[label] += 1
                placed = True
                break
        if not placed:
            if value < float(edges[0]):
                counts[labels[0]] += 1
            else:
                counts[labels[-1]] += 1
    return dict(counts)


def equal_width_bins(values: Iterable[object], bucket_count: int = 8) -> Tuple[List[float], List[str]]:
    clean = finite_values(values)
    if not clean:
        return [0.0, 1.0], ["0"]
    low = min(clean)
    high = max(clean)
    if abs(high - low) <= EPS:
        high = low + 1.0
    width = (high - low) / bucket_count
    edges = [low + width * index for index in range(bucket_count)] + [high]
    labels = [f"{edges[i]:.3g}-{edges[i + 1]:.3g}" for i in range(bucket_count)]
    return edges, labels


def wasserstein_distance(reference_values: Iterable[object], generated_values: Iterable[object]) -> float:
    ref = finite_values(reference_values)
    gen = finite_values(generated_values)
    if not ref and not gen:
        return 0.0
    if not ref or not gen:
        combined = ref + gen
        return max(combined) - min(combined) if combined else 1.0
    try:
        from scipy.stats import wasserstein_distance as scipy_wasserstein_distance

        return float(scipy_wasserstein_distance(ref, gen))
    except Exception:
        return _quantile_wasserstein(ref, gen)


def normalized_wasserstein(
    reference_values: Iterable[object],
    generated_values: Iterable[object],
    normalizer: float | None = None,
) -> float:
    ref = finite_values(reference_values)
    gen = finite_values(generated_values)
    distance = wasserstein_distance(ref, gen)
    if normalizer is None:
        combined = ref + gen
        if not combined:
            return 0.0
        normalizer = max(combined) - min(combined)
    if normalizer is None or abs(normalizer) <= EPS:
        return 0.0 if distance <= EPS else 1.0
    return distance / abs(normalizer)


def ks_statistic(reference_values: Iterable[object], generated_values: Iterable[object]) -> float:
    ref = finite_values(reference_values)
    gen = finite_values(generated_values)
    if not ref and not gen:
        return 0.0
    if not ref or not gen:
        return 1.0
    try:
        from scipy.stats import ks_2samp

        return float(ks_2samp(ref, gen).statistic)
    except Exception:
        return _ks_statistic(ref, gen)


def numeric_distribution_metrics(
    reference_values: Iterable[object],
    generated_values: Iterable[object],
    *,
    bins: Tuple[Sequence[float], Sequence[str]] | None = None,
    normalizer: float | None = None,
) -> Dict[str, object]:
    ref = finite_values(reference_values)
    gen = finite_values(generated_values)
    ref_summary = summary(ref)
    gen_summary = summary(gen)
    result: Dict[str, object] = {
        "reference": ref_summary,
        "generated": gen_summary,
        "mean_absolute_error": abs(gen_summary["mean"] - ref_summary["mean"]),
        "mean_relative_error": relative_error(gen_summary["mean"], ref_summary["mean"]),
        "std_absolute_error": abs(gen_summary["std"] - ref_summary["std"]),
        "std_relative_error": relative_error(gen_summary["std"], ref_summary["std"]),
        "wasserstein": wasserstein_distance(ref, gen),
        "normalized_wasserstein": normalized_wasserstein(ref, gen, normalizer),
        "ks_statistic": ks_statistic(ref, gen),
    }
    if bins is not None:
        edges, labels = bins
        ref_hist = bin_numeric_values(ref, edges, labels)
        gen_hist = bin_numeric_values(gen, edges, labels)
        jsd = js_divergence(ref_hist, gen_hist)
        result.update(
            {
                "bins": list(labels),
                "reference_histogram": ref_hist,
                "generated_histogram": gen_hist,
                "js_divergence": jsd,
                "js_similarity": 1.0 - jsd,
                "l1_distance": distribution_l1(ref_hist, gen_hist),
            }
        )
    return result


def categorical_distribution_metrics(
    reference_values: Iterable[object],
    generated_values: Iterable[object],
) -> Dict[str, object]:
    ref_counts = counter_from_values(reference_values)
    gen_counts = counter_from_values(generated_values)
    jsd = js_divergence(ref_counts, gen_counts)
    return {
        "reference_distribution": ref_counts,
        "generated_distribution": gen_counts,
        "js_divergence": jsd,
        "js_similarity": 1.0 - jsd,
        "l1_distance": distribution_l1(ref_counts, gen_counts),
        "cosine": counter_cosine(ref_counts, gen_counts),
    }


def primary_numeric_error(metrics: Mapping[str, object]) -> float:
    values = [
        bounded(float(metrics.get("mean_relative_error", 0.0))),
        bounded(float(metrics.get("normalized_wasserstein", 0.0))),
        bounded(float(metrics.get("ks_statistic", 0.0))),
    ]
    if "js_divergence" in metrics:
        values.append(bounded(float(metrics.get("js_divergence", 0.0))))
    return sum(values) / len(values) if values else 0.0


def primary_distribution_error(metrics: Mapping[str, object]) -> float:
    values = [
        bounded(float(metrics.get("js_divergence", 0.0))),
        bounded(float(metrics.get("l1_distance", 0.0))),
    ]
    if "cosine" in metrics:
        values.append(bounded(1.0 - float(metrics.get("cosine", 0.0))))
    return sum(values) / len(values)


def mean_bounded(values: Iterable[object]) -> float:
    clean = [bounded(float(value)) for value in values if value not in (None, "")]
    return sum(clean) / len(clean) if clean else 0.0


def _quantile_wasserstein(reference_values: Sequence[float], generated_values: Sequence[float]) -> float:
    ref = sorted(reference_values)
    gen = sorted(generated_values)
    sample_count = max(len(ref), len(gen), 1)
    total = 0.0
    for index in range(sample_count):
        q = (index + 0.5) / sample_count
        total += abs(_quantile(ref, q) - _quantile(gen, q))
    return total / sample_count


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    pos = q * (len(values) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return float(values[low])
    weight = pos - low
    return float(values[low]) * (1.0 - weight) + float(values[high]) * weight


def _ks_statistic(reference_values: Sequence[float], generated_values: Sequence[float]) -> float:
    ref = sorted(reference_values)
    gen = sorted(generated_values)
    values = sorted(set(ref) | set(gen))
    if not values:
        return 0.0
    ref_index = 0
    gen_index = 0
    max_delta = 0.0
    for value in values:
        while ref_index < len(ref) and ref[ref_index] <= value:
            ref_index += 1
        while gen_index < len(gen) and gen[gen_index] <= value:
            gen_index += 1
        ref_cdf = ref_index / len(ref)
        gen_cdf = gen_index / len(gen)
        max_delta = max(max_delta, abs(ref_cdf - gen_cdf))
    return max_delta
