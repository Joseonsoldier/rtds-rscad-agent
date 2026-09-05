"""Analytical sample fixtures; all thresholds are synthetic user-defined criteria."""
import test_environment  # isolate config and credentials before application imports
import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import test_public_release as fixtures
from rtds_agent.assessment import evaluate_results, save_result_assessment
from rtds_agent.core.state_machine import sha256_file, sha256_json

class AssessmentTests(unittest.TestCase):
    def setUp(self):
        fixtures.PublicReleaseTests.setUp(self)
        self.datafile=self.data/"samples.json"
        self.payload={"schema_version":"1.0","input_project_sha256":sha256_file(self.project),"run_id":"synthetic-run","attempt_id":"attempt-1","time_unit":"s","time_basis":"simulator_time",
                      "channels":[{"channel_id":"v","units":"V","sign_convention":"as_recorded","times":[0,1,2,3],"values":[0,1,2,1]}]}
        self.requirement={"requirement_id":"SYN-1","kind":"range","channel_id":"v","units":"V","sign_convention":"as_recorded","time_unit":"s","time_basis":"simulator_time","start_time":0,"end_time":3,"lower":0,"upper":2,"provenance":{"kind":"user_defined","reference":"synthetic test criterion only"}}
        self.request={"source":{"data_path":str(self.datafile),"data_sha256":"", "input_project":str(self.project),"input_project_sha256":sha256_file(self.project),"run_id":"synthetic-run","attempt_id":"attempt-1"},"specification":{"schema_version":"1.0","requirements":[self.requirement]},"specification_sha256":""}
        self.refresh()

    def refresh(self):
        self.datafile.write_text(json.dumps(self.payload),encoding="utf-8")
        self.request["source"]["data_sha256"]=sha256_file(self.datafile)
        self.request["specification_sha256"]=sha256_json(self.request["specification"])

    def run_result(self):
        self.refresh()
        return evaluate_results(self.request)

    def test_inclusive_range_known_min_max_and_determinism(self):
        result=self.run_result()
        self.assertEqual(result["status"],"passed")
        self.assertEqual(result["results"][0]["metrics"],{"minimum":0,"maximum":2,"sample_count":4})
        self.assertEqual(result,evaluate_results(self.request))
        self.requirement["upper"]=1.9
        self.assertEqual(self.run_result()["status"],"failed")

    def test_settling_band_after_time_is_inclusive(self):
        self.payload["channels"][0]["values"]=[3,2,1,1]
        self.requirement.update(kind="settling_band",lower=0.9,upper=1.1,settle_after=2)
        result=self.run_result()
        self.assertEqual(result["status"],"passed")
        self.assertEqual(result["results"][0]["metrics"]["sampled_settling_time"],2)
        self.requirement["settle_after"]=1
        self.assertEqual(self.run_result()["status"],"failed")

    def reference(self,values=None,times=None):
        payload=copy.deepcopy(self.payload)
        if values is not None:payload["channels"][0]["values"]=values
        if times is not None:payload["channels"][0]["times"]=times
        path=self.data/"reference.json";path.write_text(json.dumps(payload),encoding="utf-8")
        self.request["reference"]={**self.request["source"],"data_path":str(path),"data_sha256":sha256_file(path)}
        self.requirement.pop("lower",None);self.requirement.pop("upper",None)
        self.requirement.update(kind="reference_error",absolute_tolerance=1,relative_tolerance=0)

    def test_reference_error_analytic_rmse(self):
        self.reference([0,0,1,1])
        result=self.run_result()
        self.assertEqual(result["status"],"passed")
        self.assertEqual(result["results"][0]["metrics"]["max_absolute_error"],1)
        self.assertAlmostEqual(result["results"][0]["metrics"]["rmse"],math.sqrt(0.5))
        self.requirement["rmse_limit"]=0.5
        self.assertEqual(self.run_result()["status"],"failed")

    def test_reference_alignment_must_be_exact(self):
        self.reference(times=[0,0.5,2,3])
        self.assertEqual(self.run_result()["results"][0]["reasons"],["reference_time_alignment_failed"])

    def test_units_and_time_basis_must_match(self):
        for key,value in (("units","kV"),("sign_convention","positive_import")):
            with self.subTest(key=key):
                self.payload["channels"][0][key]=value
                self.assertEqual(self.run_result()["status"],"inconclusive")
                self.payload["channels"][0][key]=self.requirement[key]
        self.payload["time_basis"]="wall_clock"
        self.assertEqual(self.run_result()["status"],"inconclusive")
        self.payload["time_unit"]="ms"
        self.assertEqual(self.run_result()["status"],"inconclusive")

    def test_pu_base_is_required_and_exact(self):
        self.requirement["units"]="pu";self.payload["channels"][0]["units"]="pu"
        self.assertEqual(self.run_result()["status"],"inconclusive")
        self.requirement["pu_base"]=100;self.payload["channels"][0]["pu_base"]=100
        self.assertEqual(self.run_result()["status"],"passed")
        self.requirement["pu_base"]=200
        self.assertEqual(self.run_result()["status"],"inconclusive")

    def test_nonmonotonic_duplicate_nonfinite_empty_and_short_data(self):
        for times,values in [([0,2,1,3],[0,1,2,1]),([0,1,1,3],[0,1,2,1]),([0,1,2,3],[0,float("nan"),2,1]),([0,1,2,3],[0,float("inf"),2,1]),([],[]),([0,1],[0,1]),([0,1,2,3],[0,True,2,1])]:
            with self.subTest(times=times,values=values):
                self.payload["channels"][0].update(times=times,values=values)
                self.assertEqual(self.run_result()["status"],"inconclusive")

    def test_empty_interval_and_gap_fail_quality(self):
        self.requirement.update(start_time=0.2,end_time=0.8)
        self.assertEqual(self.run_result()["status"],"inconclusive")
        self.requirement.update(start_time=0,end_time=3,max_sample_gap_seconds=0.5)
        self.assertIn("sample_gap_exceeds_specification",self.run_result()["results"][0]["reasons"])

    def test_stale_data_project_spec_and_run_identity_rejected(self):
        for key in ("data_sha256","input_project_sha256"):
            original=self.request["source"][key];self.request["source"][key]="0"*64
            with self.assertRaises(ValueError):evaluate_results(self.request)
            self.request["source"][key]=original
        self.request["specification_sha256"]="0"*64
        with self.assertRaises(ValueError):evaluate_results(self.request)
        self.refresh();self.request["source"]["attempt_id"]="old-attempt"
        with self.assertRaises(ValueError):evaluate_results(self.request)

    def test_no_criteria_and_metrics_only_never_pass(self):
        self.request["specification"]["requirements"]=[]
        result=self.run_result()
        self.assertEqual(result["status"],"not_evaluated")
        self.assertEqual(result["channel_summaries"][0]["metrics"]["maximum"],2)
        self.request["specification"]["requirements"]=[self.requirement]
        self.requirement.pop("lower");self.requirement.pop("upper");self.requirement["kind"]="min_max"
        self.assertEqual(self.run_result()["status"],"not_evaluated")

    def test_invalid_spec_is_input_error(self):
        for key,value in (("start_time",4),("lower",3),("upper",float("inf")),("unsafe",True)):
            original=copy.deepcopy(self.requirement)
            self.requirement[key]=value
            with self.assertRaises(ValueError):self.run_result()
            self.requirement.clear();self.requirement.update(original)

    def test_read_only_and_separate_report_without_workflow_mutation(self):
        before={p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch("rtds_agent.execution._backend") as backend:
            result=evaluate_results(self.request)
            backend.assert_not_called()
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        saved=save_result_assessment(self.request)
        self.assertFalse(saved["workflow_modified"])
        self.assertEqual(saved,save_result_assessment(self.request))
        self.assertEqual(json.loads(Path(saved["artifact"]["path"]).read_text(encoding="utf-8")),result)
        self.assertEqual(sha256_file(self.project),self.request["source"]["input_project_sha256"])

    def test_data_path_escape_and_unknown_channel(self):
        self.request["source"]["data_path"]=str(self.config)
        with self.assertRaises(ValueError):evaluate_results(self.request)
        self.request["source"]["data_path"]=str(self.datafile)
        self.requirement["channel_id"]="unknown"
        self.assertEqual(self.run_result()["status"],"inconclusive")

    def test_bounded_sample_preview_and_stale_pagination(self):
        from rtds_agent.assessment import read_result_samples
        first=read_result_samples(self.request["source"],"v",0,3,limit=2)
        self.assertEqual(first["next_offset"],2)
        second=read_result_samples(self.request["source"],"v",0,3,offset=2,limit=2)
        self.assertEqual(first["samples"]+second["samples"],[{"time":t,"value":v} for t,v in zip([0,1,2,3],[0,1,2,1])])
        self.assertIsNone(second["next_offset"])
        self.datafile.write_text("changed",encoding="utf-8")
        with self.assertRaises(ValueError):read_result_samples(self.request["source"],"v",0,3,offset=2)

    def test_unsupported_large_integers_and_interrupted_report(self):
        self.payload["channels"][0]["values"][0]=10**400
        self.assertEqual(self.run_result()["status"],"inconclusive")
        self.payload["channels"][0]["values"][0]=0
        self.requirement["upper"]=10**400
        with self.assertRaises(ValueError):self.run_result()
        self.requirement["upper"]=2;self.refresh()
        with patch("rtds_agent.assessment.os.link",side_effect=OSError("synthetic publication failure")):
            with self.assertRaises(OSError):save_result_assessment(self.request)
        self.assertEqual(list((self.data/"assessments").iterdir()),[])
