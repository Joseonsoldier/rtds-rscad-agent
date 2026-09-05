"""Sampled engineering metrics. Calculations and supplied acceptance are separate."""
import math

OPTIONS = {
    "voltage_nadir": set(), "frequency_nadir": set(), "RoCoF": set(),
    "voltage_recovery_time": {"lower", "upper", "event_time"},
    "active_power_recovery": {"lower", "upper", "event_time"},
    "reactive_power_peak": set(), "reactive_current_injection": set(),
    "overshoot": {"baseline"}, "settling_time": {"lower", "upper", "event_time"},
    "oscillation_frequency": {"baseline"}, "damping_ratio": {"baseline"},
    "angle_separation": {"other_channel_id"}, "THD": {"fundamental_hz", "harmonics"},
    "current_limit_duration": {"threshold"},
}


def validate_metric(req):
    name, options = req["metric"], req["metric_options"]
    if name not in OPTIONS or set(options) != OPTIONS[name]:
        raise ValueError("Metric options must exactly match the documented metric")
    if "lower" in options and options["lower"] > options["upper"]:
        raise ValueError("Metric band is reversed")
    if "event_time" in options and not req["start_time"] <= options["event_time"] < req["end_time"]:
        raise ValueError("Metric event_time must be inside the interval before its end")
    if name == "RoCoF" and req["units"] != "Hz": raise ValueError("RoCoF requires Hz samples")
    if name == "angle_separation" and req["units"] not in {"deg","rad"}: raise ValueError("Angle separation requires deg or rad")
    if name == "current_limit_duration" and options["threshold"] < 0: raise ValueError("Current magnitude threshold must be nonnegative")
    acceptance = req.get("metric_acceptance")
    if acceptance and acceptance["lower"] > acceptance["upper"]: raise ValueError("Metric acceptance range is reversed")


def compute_metric(req, times, values, other_values=None):
    validate_metric(req)
    name, op, units = req["metric"], req["metric_options"], req["units"]
    value, method = None, "discrete_samples"
    if name in {"voltage_nadir","frequency_nadir"}: value = min(values)
    elif name == "RoCoF":
        value = max(abs((b-a)/(tb-ta)) for ta,tb,a,b in zip(times,times[1:],values,values[1:]))
        units, method = "Hz/s", "maximum_absolute_adjacent_difference"
    elif name in {"voltage_recovery_time","active_power_recovery","settling_time"}:
        eligible = [i for i,t in enumerate(times) if t >= op["event_time"]]
        last_out = max((i for i in eligible if not op["lower"] <= values[i] <= op["upper"]), default=eligible[0]-1)
        if last_out+1 < len(times): value = times[last_out+1]-op["event_time"]
        units, method = "s", "first_sample_after_last_band_violation_until_capture_end"
    elif name == "reactive_power_peak": value, method = max(map(abs,values)), "maximum_absolute_sample"
    elif name == "reactive_current_injection": value, method = max(values), "maximum_signed_sample_under_declared_sign_convention"
    elif name == "overshoot": value = max(0.0,max(values)-op["baseline"])
    elif name == "current_limit_duration":
        value = sum(b-a for a,b,v in zip(times,times[1:],values) if abs(v) >= op["threshold"])
        units, method = "s", "left_sample_hold_magnitude_at_or_above_threshold"
    elif name == "angle_separation":
        if other_values is None or len(other_values) != len(values): raise ValueError("Angle separation requires exact aligned comparison samples")
        period = 360.0 if units == "deg" else 2*math.pi
        value = max(abs((a-b+period/2)%period-period/2) for a,b in zip(values,other_values))
        method = "maximum_principal_wrapped_angle_difference"
    elif name == "oscillation_frequency":
        crossings = []
        for a,b,va,vb in zip(times,times[1:],values,values[1:]):
            if va < op["baseline"] <= vb:
                crossings.append(a+(b-a)*(op["baseline"]-va)/(vb-va))
        if len(crossings) < 3: raise ValueError("Oscillation frequency requires at least three rising baseline crossings")
        value = (len(crossings)-1)/(crossings[-1]-crossings[0])
        units, method = "Hz", "mean_rising_crossing_period_linear_crossing_estimate"
    elif name == "damping_ratio":
        peaks = [v-op["baseline"] for a,v,b in zip(values,values[1:],values[2:]) if v > a and v >= b and v > op["baseline"]]
        if len(peaks) < 3 or any(a <= b for a,b in zip(peaks,peaks[1:])):
            raise ValueError("Damping estimate requires three strictly decaying positive peaks about the declared baseline")
        decrement = sum(math.log(a/b) for a,b in zip(peaks,peaks[1:]))/(len(peaks)-1)
        value = decrement/math.sqrt(4*math.pi**2+decrement**2)
        units, method = "1", "single_mode_log_decrement_estimate; single-mode assumption not verified"
    elif name == "THD":
        n, frequency, harmonics = len(times), op["fundamental_hz"], op["harmonics"]
        dt = (times[-1]-times[0])/(n-1)
        if any(not math.isclose(b-a,dt,rel_tol=1e-7,abs_tol=1e-12) for a,b in zip(times,times[1:])):
            raise ValueError("THD requires uniform sampling")
        cycles = frequency*n*dt
        if cycles < 2 or not math.isclose(cycles,round(cycles),rel_tol=0,abs_tol=1e-6) or frequency*harmonics >= 0.5/dt:
            raise ValueError("THD requires >=2 whole fundamental cycles in N*dt and harmonics below Nyquist")
        # Fixed requested harmonics only; no FFT dependency or arbitrary expression.
        amplitudes = []
        mean = sum(values)/n
        for h in range(1,harmonics+1):
            angle = 2*math.pi*h*frequency*dt
            real = sum((v-mean)*math.cos(angle*i) for i,v in enumerate(values))*2/n
            imag = sum((v-mean)*math.sin(angle*i) for i,v in enumerate(values))*2/n
            amplitudes.append(math.hypot(real,imag))
        if amplitudes[0] <= max(1e-15,max(amplitudes)*1e-12): raise ValueError("Fundamental amplitude is absent or numerically unresolved")
        value = math.hypot(*amplitudes[1:])/amplitudes[0]*100
        units, method = "%", "coherent_rectangular_DFT_of_explicit_harmonics_2_through_H"
    if value is None: raise ValueError("Recovery was not observed within the supplied capture")
    if not math.isfinite(value): raise ValueError("Metric calculation overflow")
    result = {"metric":name,"value":value,"units":units,"method":method,"sample_count":len(times)}
    criterion = req.get("metric_acceptance")
    if criterion and criterion["units"] != units: raise ValueError("Metric acceptance units mismatch")
    status = "not_evaluated" if criterion is None else "passed" if criterion["lower"] <= value <= criterion["upper"] else "failed"
    return result,status
