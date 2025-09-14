# This code is part of a Qiskit project.
#
# (C) Copyright IBM 2022, 2025.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
"""
Gradient of probabilities with parameter shift
"""

from __future__ import annotations

from collections.abc import Sequence

from qiskit.circuit import Parameter, QuantumCircuit
from qiskit.quantum_info.operators.base_operator import BaseOperator

from qiskit_algorithms.custom_types import EVAL_OBSERVABLE

from ...exceptions import AlgorithmError
from ..base.base_estimator_gradient import BaseEstimatorGradient
from ..base.estimator_gradient_result import EstimatorGradientResult
from ..utils import _make_param_shift_parameter_values


class ParamShiftEstimatorGradient(BaseEstimatorGradient):
    """
    Compute the gradients of the expectation values by the parameter shift rule [1].

    **Reference:**
    [1] Schuld, M., Bergholm, V., Gogolin, C., Izaac, J., and Killoran, N. Evaluating analytic
    gradients on quantum hardware, `DOI <https://doi.org/10.1103/PhysRevA.99.032331>`_
    """

    SUPPORTED_GATES = [
        "x",
        "y",
        "z",
        "h",
        "rx",
        "ry",
        "rz",
        "p",
        "cx",
        "cy",
        "cz",
        "ryy",
        "rxx",
        "rzz",
        "rzx",
    ]

    def _run(
        self,
        circuits: Sequence[QuantumCircuit],
        observables: Sequence[EVAL_OBSERVABLE],
        parameter_values: Sequence[Sequence[float]],
        parameters: Sequence[Sequence[Parameter]],
        *,
        precision: float | Sequence[float] | None,
    ) -> EstimatorGradientResult:
        """Compute the gradients of the expectation values by the parameter shift rule."""
        g_circuits, g_parameter_values, g_parameters = self._preprocess(
            circuits, parameter_values, parameters, self.SUPPORTED_GATES
        )

        if self._transpiler is not None:
            g_circuits = self._transpiler.run(g_circuits, **self._transpiler_options)
            observables = [
                obs.apply_layout(circuit.layout) for (circuit, obs) in zip(g_circuits, observables)
            ]

        results = self._run_unique(
            g_circuits, observables, g_parameter_values, g_parameters, precision=precision
        )
        return self._postprocess(results, circuits, parameter_values, parameters)

    def _run_unique(
        self,
        circuits: Sequence[QuantumCircuit],
        observables: Sequence[BaseOperator],
        parameter_values: Sequence[Sequence[float]],
        parameters: Sequence[Sequence[Parameter]],
        *,
        precision: float | Sequence[float] | None,
    ) -> EstimatorGradientResult:
        """Compute the estimator gradients on the given circuits."""
        has_transformed_precision = False

        if isinstance(precision, float) or precision is None:
            precision = [precision] * len(circuits)
            has_transformed_precision = True

        metadata = []
        pubs = []

        if not (
            len(circuits)
            == len(observables)
            == len(parameters)
            == len(parameter_values)
            == len(precision)
        ):
            raise ValueError(
                f"circuits, observables, parameters, parameter_values and precision must have the same"
                f"length, but have respective lengths {len(circuits)},  {len(observables)}, "
                f"{len(parameters)}, {len(parameter_values)} and {len(precision)}."
            )

        for circuit, observable, parameter_values_, parameters_, precision_ in zip(
            circuits, observables, parameter_values, parameters, precision
        ):
            metadata.append({"parameters": parameters_})
            # Make parameter values for the parameter shift rule.
            param_shift_parameter_values = _make_param_shift_parameter_values(
                circuit, parameter_values_, parameters_
            )
            # Combine inputs into a single job to reduce overhead.
            pubs.append((circuit, observable, param_shift_parameter_values, precision_))

        # Run the single job with all circuits.
        job = self._estimator.run(pubs)
        try:
            results = job.result()
        except Exception as exc:
            raise AlgorithmError("Estimator job failed.") from exc

        # Compute the gradients.
        gradients = []

        for result in results:
            evs = result.data.evs
            n = evs.shape[0]
            gradient_ = (evs[: n // 2] - evs[n // 2 :]) / 2
            gradients.append(gradient_)

        if has_transformed_precision:
            precision = precision[0]

            if precision is None:
                precision = results[0].metadata["target_precision"]
        else:
            for i, (precision_, result) in enumerate(zip(precision, results)):
                if precision_ is None:
                    precision[i] = results[i].metadata["target_precision"]

        return EstimatorGradientResult(gradients=gradients, metadata=metadata, precision=precision)
