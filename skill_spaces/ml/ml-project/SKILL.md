---
name: ml-project
description: >-
  Frames, builds and evaluates a machine-learning model: the decision and the
  cost of errors, a trivial baseline then a simple model, train/validation/test
  splits that match the future (stratified, time-based or grouped), a data
  leakage checklist, preprocessing inside a pipeline, cross-validation, the
  right metrics, overfitting checks, a bounded search, interpretability,
  fairness checks, reproducibility and a model card with a monitoring plan.
  Use for training or evaluating a model. Se déclenche sur : machine learning,
  entraîner un modèle, classification, régression, prédiction, scikit-learn,
  surapprentissage, évaluation de modèle, MLOps.
---

# ml-project
Produces `train.py` (reproducible training and evaluation) and
`model-report.md` written as a model card. Without ML libraries installed,
the same files as a plan and code for the user to run.

## Before you start
| Input | Where | If missing |
|---|---|---|
| Decision and target | task, handoffs | write them as you understand them; record it |
| Data | target folders, data handoff (cleaned file, profile) | list the data needed under For the user; stop at the plan |
| Error costs | task | false negatives and false positives equally costly; say so |
| Constraints | task: latency, interpretability, hardware | CPU only, interpretable model preferred |
| Libraries | `python3 -c "import sklearn, numpy, pandas; print(sklearn.__version__)"` | plan and code only; `pip install scikit-learn` listed For the user |

## Method
1. **Frame**: task type (binary or multi-class classification, regression,
   ranking, clustering, forecasting); unit of prediction (one row = ?); when
   the prediction is made and what is known at that moment.
2. **Metric** tied to the decision (table below) and the target value that
   would make the model useful.
3. **Baseline**: majority class / mean / last value / seasonal naive; scored
   the same way as every model.
4. **Split** like the future:
   - classification: stratified split, then stratified k-fold CV (k = 5);
   - temporal data: train on the past, validate on the next period
     (`TimeSeriesSplit`), never shuffle;
   - rows sharing an entity (user, patient, device): `GroupKFold` so one
     entity never sits on both sides;
   - hold out a test set first and do not look at it until the end.
5. **Leakage check** (checklist) before training anything.
6. **Pipeline**: imputation, encoding and scaling inside a scikit-learn
   `Pipeline`/`ColumnTransformer`, fitted per fold.
7. **Simple model**: logistic or linear regression (regularised), then a tree
   ensemble (random forest or gradient boosting such as
   `HistGradientBoosting*`). Deep learning only for images, audio, text at
   scale, or when the simple models plateau far below the target.
8. **Search** on a budget: `RandomizedSearchCV` with a fixed number of
   iterations; record the grid and the best parameters.
9. **Diagnose**: train vs validation gap (overfitting), learning curve (more
   data or more capacity?), confusion matrix and error analysis on
   misclassified examples, calibration for probabilities used as scores.
10. **Interpret**: permutation importance on validation; SHAP only if
    installed; partial dependence for key features.
11. **Fairness**: metrics per relevant subgroup (where the data has the
    attribute and the use affects people); report gaps.
12. **Test once**, then write `train.py` and `model-report.md`.

## Checklists

### Data leakage
| Leak | Example | Guard |
|---|---|---|
| Target in features | `refund_issued` used to predict churn | ask "is this known at prediction time?" for every column |
| Future information | rolling mean computed over the whole series | features use only past data; time-based split |
| Preprocessing on all data | scaler or imputer fitted before the split | fit inside the pipeline per fold |
| Duplicates across splits | the same customer or image in train and test | dedupe; group-aware split |
| Selection on test | features or models chosen by test score | test touched once, at the end |

### Metrics
| Problem | Metric | Note |
|---|---|---|
| Balanced classification | accuracy, F1, ROC-AUC | report the confusion matrix |
| Rare positives | PR-AUC, recall at a fixed precision (or the reverse) | accuracy is misleading |
| Probabilities used as risk | log loss, Brier score, calibration curve | calibrate if needed |
| Regression | MAE (in the target's unit), RMSE (penalises big errors), R² | compare to the mean baseline |
| Ranking / recommendation | NDCG@k, MAP@k, recall@k | k from the product |
| Clustering | silhouette score plus a human check of clusters | no ground truth: be modest |
| Forecasting | MAE or MAPE (not when values near 0), vs seasonal naive | backtest over several periods |

Report the mean and standard deviation across folds; a difference within one
standard deviation is not a win.

### Reproducibility
Seeds (`random_state`) everywhere; library versions printed; SHA-256 of the
data file printed; the exact command in the report; models saved with the
version of the code that trained them.

### Deployment and monitoring (plan)
Batch or online scoring; input validation (schema, ranges); drift on inputs
(population stability or distribution tests) and on predictions; performance
tracked when labels arrive; retraining trigger (schedule or drift threshold);
rollback to the previous model.

## Deliverable
In the shared work folder: `train.py` (prints baseline and model scores, the
seeds, versions and data hash; saves the model when asked) and
`model-report.md` (translate the headings into the user's language):

```markdown
# Model card — <model>
## Summary
<task, best model, its validation score vs baseline, test score, main limit>
## Intended use and out-of-scope uses
## Data
| Source | Rows | Period | Target balance | Split |
## Method
<features, pipeline, models tried, search budget>
## Results
| Model | CV mean ± sd | Validation | Test (final) |
| Baseline | | | |
## Error analysis
## Interpretability
## Fairness
| Group | n | Metric | Gap |
## Limitations and risks
## Monitoring and retraining
## Reproduce
`python3 train.py --data <file>` — seed, versions, data hash
## Decisions
## Next steps
```

## Pitfalls
- No baseline: a 95 % accuracy on 95 % negatives is worthless.
- Shuffling time series, or the same entity on both sides of the split.
- Tuning on the test set, or reporting the best of many test runs.
- Accuracy on imbalanced data; ROC-AUC alone when positives are rare.
- Scaling or imputing before splitting.
- Deep learning on a small tabular dataset that a boosted tree handles.
- Feature importance read as causation.
- Numbers in the report that `train.py` does not print.
