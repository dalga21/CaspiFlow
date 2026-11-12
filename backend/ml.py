"""Reproducible synthetic benchmark. No real-world accuracy is claimed."""
import hashlib
import json
import math
import platform
from dataclasses import dataclass

import numpy as np
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

FEATURES = [
    ('wind_m_s', 'Ветер', 'м/с'),
    ('wave_m', 'Высота волны', 'м'),
    ('port_load_percent', 'Загрузка узла', '%'),
    ('historical_delay_hours', 'Историческая задержка', 'ч'),
    ('distance_km', 'Длина маршрута', 'км'),
    ('transfers', 'Перегрузки', ''),
]


@dataclass
class ModelBundle:
    estimator: RandomForestRegressor
    metrics: dict
    radius: float
    bounds: np.ndarray


def fit_model(rows):
    x = np.array([json.loads(r['features']) for r in rows], dtype=float)
    y = np.array([r['delay'] for r in rows], dtype=float)
    if len(y) < 100 or x.shape != (len(y), 6) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Invalid training data')
    # Split indices BEFORE fitting. IID synthetic rows have no voyage/group/time identity.
    train_cal, test = train_test_split(np.arange(len(y)), test_size=.2, random_state=42)
    train, calibration = train_test_split(train_cal, test_size=.25, random_state=43)
    fingerprints = [hashlib.sha256(row.tobytes()).hexdigest() for row in x]
    groups = [set(fingerprints[i] for i in ids) for ids in (train, calibration, test)]
    overlaps = sum(len(groups[a] & groups[b]) for a, b in ((0, 1), (0, 2), (1, 2)))
    if overlaps:
        raise ValueError('Duplicate feature rows across splits; use grouped splitting')
    # Physical prior for this synthetic generator: worse weather / higher load cannot
    # decrease delay. Other variables remain unconstrained. No hyperparameter search.
    estimator = RandomForestRegressor(
        n_estimators=100, max_depth=12, min_samples_leaf=3, random_state=42,
        n_jobs=1, monotonic_cst=[1, 1, 1, 0, 0, 0],
    )
    estimator.fit(x[train], y[train])
    calibration_errors = np.abs(y[calibration] - estimator.predict(x[calibration]))
    level = min(1, math.ceil((len(calibration) + 1) * .9) / len(calibration))
    radius = float(np.quantile(calibration_errors, level, method='higher'))
    predicted = estimator.predict(x[test])
    baseline = np.full(len(test), np.median(y[train]))
    # Global held-out importance: change in MAE after shuffling one input.
    importance = permutation_importance(
        estimator, x[test], y[test], scoring='neg_mean_absolute_error',
        n_repeats=10, random_state=44, n_jobs=1,
    )
    factors = sorted([
        {'key': key, 'label': label, 'unit': unit,
         'mae_increase_hours': round(float(importance.importances_mean[i]), 4),
         'std_hours': round(float(importance.importances_std[i]), 4)}
        for i, (key, label, unit) in enumerate(FEATURES)
    ], key=lambda f: f['mae_increase_hours'], reverse=True)
    data_hash = hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest()
    model_hash = hashlib.sha256((data_hash + json.dumps(estimator.get_params(), sort_keys=True)).encode() + train.tobytes() + calibration.tobytes() + test.tobytes()).hexdigest()[:12]
    metrics = {
        'name': 'Random Forest', 'version': model_hash, 'synthetic': True,
        'seed': 42, 'split_seed': 43, 'permutation_seed': 44,
        'train_samples': len(train), 'calibration_samples': len(calibration), 'test_samples': len(test),
        'mae_hours': round(float(mean_absolute_error(y[test], predicted)), 4),
        'rmse_hours': round(float(root_mean_squared_error(y[test], predicted)), 4),
        'r2': round(float(r2_score(y[test], predicted)), 4),
        'train_mae_hours': round(float(mean_absolute_error(y[train], estimator.predict(x[train]))), 4),
        'baseline_mae_hours': round(float(mean_absolute_error(y[test], baseline)), 4),
        'baseline_rmse_hours': round(float(root_mean_squared_error(y[test], baseline)), 4),
        'baseline_r2': round(float(r2_score(y[test], baseline)), 4),
        'residual_p90_hours': round(radius, 4),
        'interval_method': 'split conformal, absolute residuals, calibration only, nominal 90%',
        'test_interval_coverage': round(float(np.mean(np.abs(y[test]-predicted) <= radius)), 4),
        'features': [f[0] for f in FEATURES],
        'split': 'IID synthetic, 60% train / 20% calibration / 20% test; no tuning on test',
        'duplicate_feature_rows': len(fingerprints)-len(set(fingerprints)),
        'cross_split_overlap': overlaps, 'dataset_sha256': data_hash,
        'parameters': estimator.get_params(),
        'versions': {'python': platform.python_version(), 'numpy': np.__version__, 'sklearn': sklearn.__version__},
        'explanation': {'method': 'permutation_importance', 'scope': 'global held-out test',
                        'repeats': 10, 'scoring': 'neg_mean_absolute_error', 'factors': factors},
        'limitation': 'Только синтетические IID-рейсы. Нет проверки на реальных перевозках. '
                      'Диапазон откалиброван отдельно; покрытие на реальных данных не гарантируется. '
                      'Важность факторов глобальная, не причинность и не вклад в отдельный прогноз.',
    }
    return ModelBundle(estimator, metrics, radius, np.array([x[train].min(axis=0), x[train].max(axis=0)]))
