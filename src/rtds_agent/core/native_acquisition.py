"""Bounded SDK signal-array acquisition. No connection, Runtime start or policy API."""
from __future__ import annotations
import copy
import math
from pathlib import Path
import re
import zipfile
from .runtime_binding import bind_live_control
from .runtime_parser import parse_runtime_layout
from .state_machine import sha256_file, sha256_json

MODE = "native_signal_arrays"
MAX_SAMPLES = 100000


def native_channels(channels):
    result=[]
    for row in channels:
        item=copy.deepcopy(row)
        for name in ("channel_id","signal_path","units","sign_convention"):
            if not isinstance(item.get(name),str) or not item[name].strip() or len(item[name])>500:
                raise ValueError(f"Unresolved native capture metadata: {name}")
        if item.get("time_basis")!="simulator_time":raise ValueError("Native time basis requires explicit simulator_time evidence")
        base=item.get("pu_base")
        if (base is not None and (type(base) not in (int,float) or not math.isfinite(base) or base<=0)) or (item["units"]=="pu" and base is None):
            raise ValueError("Unresolved or invalid native pu base")
        evidence=item.get("metadata_evidence")
        if not isinstance(evidence,dict) or set(evidence)!={"source_sha256","locator"} or not re.fullmatch("[a-f0-9]{64}",str(evidence.get("source_sha256"))) or not isinstance(evidence.get("locator"),str) or not 1<=len(evidence["locator"].strip())<=1000:
            raise ValueError("Native units/sign/time metadata requires a source hash and exact locator")
        identity=item.get("runtime_identity")
        if not isinstance(identity,dict) or set(identity)!={"object_uuid","object_name","object_subpage"}:
            raise ValueError("Native capture requires an exact graph identity")
        if type(identity["object_uuid"]) is not int or not 0<=identity["object_uuid"]<=9999999999999999:
            raise ValueError("Invalid native graph ID")
        for name in ("object_name","object_subpage"):
            if not isinstance(identity[name],str) or not 1<=len(identity[name].strip())<=256:raise ValueError("Unresolved native graph scope")
        keep=("channel_id","signal_path","units","sign_convention","time_basis","metadata_evidence","runtime_identity")
        result.append({**{k:item[k] for k in keep},"pu_base":base})
    if not 1<=len(result)<=64 or len({r['channel_id'] for r in result})!=len(result) or len({r['signal_path'] for r in result})!=len(result):
        raise ValueError("Native channels must have unique IDs/paths within bounds")
    return result


def validate_grounding(channels, hashes):
    for row in channels:
        if row["metadata_evidence"]["source_sha256"] not in hashes:
            raise ValueError("Unresolved native metadata: evidence is not a bound model or grounding source")


def discover_saved_signals(project, channels):
    """Require one explicit, unambiguous saved graph/curve per requested path."""
    if Path(project).stat().st_size>128*1024*1024:raise ValueError('Native acquisition project exceeds 128 MiB')
    with zipfile.ZipFile(project) as archive:
        names=[n for n in archive.namelist() if n.lower().endswith('.rtx')]
        if len(names)!=1 or len(archive.namelist())!=len(set(archive.namelist())) or archive.getinfo(names[0]).file_size>16*1024*1024:raise ValueError("Native acquisition requires one bounded saved RTX")
        parsed=parse_runtime_layout(archive.read(names[0]).decode('utf-8-sig'))
    discovered=[]
    for channel in channels:
        matches=[]
        for plot in parsed['records']:
            for graph in plot['graphs']:
                for curve in graph['curves']:
                    for ref in curve['references']:
                        if ref['stored_signal_path']==channel['signal_path']:matches.append((plot,graph,curve,ref))
        if len(matches)!=1:raise ValueError("Saved native signal is missing or ambiguous: "+channel['channel_id'])
        plot,graph,curve,ref=matches[0];identity=channel['runtime_identity']
        if plot['identity_status']!='stored_unique' or graph['identity_status']!='stored_unique' or len(curve['references'])!=1 or curve['field_ambiguities'] or ref['field_ambiguities'] or ref['draft_component_id'] is None:
            raise ValueError("Saved native graph/reference identity is unresolved")
        if graph['component_id']!=identity['object_uuid'] or graph['fields'].get('NAME')!=identity['object_name']:
            raise ValueError("Saved native graph does not match the requested identity")
        discovered.append({'channel_id':channel['channel_id'],'signal_path':channel['signal_path'],
            'graph_id':graph['component_id'],'plot_container_id':plot['component_id'],
            'stored_draft_comp_id':ref['draft_component_id'],'source_line':ref['source_line'],
            'live_target_verified':False})
    return discovered


def sampling(times):
    dt=(times[-1]-times[0])/(len(times)-1) if len(times)>1 else None
    uniform=dt is not None and dt>0 and all(math.isclose(b-a,dt,rel_tol=1e-7,abs_tol=1e-12) for a,b in zip(times,times[1:]))
    return {'sample_interval_s':dt if uniform else None,'sample_rate_hz':1/dt if uniform else None,
            'sampling':'uniform' if uniform else 'nonuniform_or_single_sample'}


class NativeAcquisition:
    """One owned pull session. Local stop closes dispatch; it is not an SDK abort."""
    def __init__(self, case, project, channels, context, *, minimum_samples=2, maximum_samples=MAX_SAMPLES):
        if set(context)!={'run_id','attempt_id','input_project_sha256'} or not all(isinstance(context[k],str) and context[k] for k in context):
            raise ValueError('Native acquisition needs bound run/attempt/project identity')
        self.case=case;self.project=Path(project);self.channels=native_channels(channels);self.context=copy.deepcopy(context)
        if type(minimum_samples) is not int or type(maximum_samples) is not int or not 2<=minimum_samples<=maximum_samples<=MAX_SAMPLES:raise ValueError('Native sample limits are invalid')
        self.minimum=minimum_samples;self.maximum=maximum_samples;self.handles={};self.total=0
        self.evidence={'schema_version':'1.0','mode':MODE,'context':copy.deepcopy(context),'channels':{},
            'state':'created','capture_success':False,'dispatch_stopped':False,'resources_closed':False,
            'stop_mechanism':'local_pull_dispatch_only','remote_abort_supported':False,'atomic_snapshot_verified':False,
            'integration_qualified':False,'freshness_verified':False,'recovery_order':[],
            'recovery':{k:'pending' for k in ('stop_acquisition_dispatch','restore_controls','stop_runtime','close_owned_acquisition_handles')}}
        self._check_source()
        self.evidence['discovery']=discover_saved_signals(self.project,self.channels)

    def _check_source(self):
        if sha256_file(self.project)!=self.context['input_project_sha256']:raise ValueError('Native acquisition input hash changed')

    def _bind(self, channel):
        _,receipt=bind_live_control(self.case,self.project,self.context['input_project_sha256'],
            {**channel['runtime_identity'],'object_type':'plot'})
        handle=self.case.get_signal(channel['signal_path'])
        if handle is None or type(handle.unique_id) is not str or handle.unique_id!=channel['signal_path'] or handle.parent is not self.case.runtime:
            raise ValueError('Native signal handle does not match exact path/Runtime owner')
        return handle,receipt

    def bind(self):
        if self.evidence['state']!='created':raise ValueError('Native acquisition cannot rebind a used session')
        for channel in self.channels:
            handle,receipt=self._bind(channel);self.handles[channel['channel_id']]=handle
            self.evidence['channels'][channel['channel_id']]={**copy.deepcopy(channel),**self.context,
                'binding':receipt,'signal_id':handle.unique_id,'metadata_status':'source_hash_bound_declaration',
                'metadata_semantics_independently_verified':False,'sample_interval_s':None,'sample_rate_hz':None,
                'time_source':'SDK Signal.get_time_data generated plot axis','time_origin_independently_verified':False,
                'signal_identity_source':'SDK request path and current Runtime owner; no independent remote ID'}
        self.evidence['state']='bound'

    def start(self):
        if self.evidence['state']!='bound':raise ValueError('Native acquisition is not bound')
        self.evidence['state']='acquiring'

    def read(self):
        if self.evidence['state']!='acquiring' or self.evidence['dispatch_stopped']:raise ValueError('Native acquisition is not active')
        output={}
        for channel in self.channels:
            self._check_source();handle,receipt=self._bind(channel)
            # SDK arrays are separate reads. Equal axes reject detectable window
            # changes; they do not prove an atomic capture or simulator-time events.
            times=handle.get_time_data();values=handle.get_data();after=handle.get_time_data()
            if not isinstance(times,list) or not isinstance(values,list) or not isinstance(after,list) or times!=after:
                raise ValueError('Native signal time window changed or arrays are unavailable')
            if not self.minimum<=len(times)<=self.maximum or len(times)!=len(values) or self.total+len(times)>MAX_SAMPLES:
                raise ValueError('Native signal samples are missing, mismatched or exceed bounds')
            if not all(type(v) in (int,float) and math.isfinite(v) for v in times+values+after) or any(a>=b for a,b in zip(times,times[1:])):
                raise ValueError('Native signal samples are nonnumeric/nonfinite or time is not increasing')
            times=[float(v) for v in times];values=[float(v) for v in values]
            self._check_source();self._bind(channel)
            cid=channel['channel_id'];self.total+=len(times)
            output[cid]={'times':list(times),'values':list(values)}
            self.evidence['channels'][cid].update(sampling(times),sample_count=len(times),binding=receipt,
                time_axis_consistency='equal_before_and_after_values',samples_sha256=sha256_json(output[cid]))
        self.evidence['capture_success']=True;self.evidence['state']='captured'
        return output

    def stop(self):
        self.evidence['dispatch_stopped']=True
        self.evidence['recovery_order'].append('stop_acquisition_dispatch')
        self.evidence['recovery']['stop_acquisition_dispatch']='succeeded'
        self.evidence['state']='stopped'

    def close(self):
        if not self.evidence['dispatch_stopped']:raise ValueError('Stop acquisition dispatch before releasing handles')
        self.handles.clear();self.case=None
        self.evidence['resources_closed']=True;self.evidence['state']='closed'
        self.evidence['recovery_order'].append('close_owned_acquisition_handles')
        self.evidence['recovery']['close_owned_acquisition_handles']='succeeded'
