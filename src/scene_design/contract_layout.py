"""Deterministic contract checks over actual frame geometry (no synthetic render)."""
import math
from src.scene_design import system_contract as system
from src.scene_design.frame_clock import frame_at


class ContractLayoutAudit:
    def __init__(self, telemetry, bundle, plan):
        self.telemetry, self.bundle, self.plan = telemetry, bundle, plan
        self.objects = {o['id']: o for o in plan['objects']}
        self.hud_baselines, self.rigid_baselines, self.hud_poses = {}, {}, {}
        self.rigid_memberships = {}
        self.seen = set()
        self.phase_events = []

    def issue(self, code, ids, time, problem, rule, owner='code_generator', occurrence=None):
        key = (code, tuple(ids), occurrence)
        if key not in self.seen:
            self.seen.add(key)
            self.telemetry.issues.append(dict(code=code, category='layout', object_ids=list(ids),
                time=round(time, 6), problem=problem, evidence=problem, rule=rule, owner=owner,
                fix='Repair code to match the validated contract and timeline; preserve approved criteria'))

    def candidate(self, ids, time, problem):
        key = ('candidate', tuple(ids), problem)
        if key not in self.seen and len(self.telemetry.candidates) < 100:
            self.seen.add(key)
            self.telemetry.candidates.append(dict(object_ids=list(ids), time=round(time, 6),
                problem=problem, bbox_only=True, owner='vision_reviewer'))

    def capture(self, objects, frame, count):
        fps = self.telemetry.fps
        times = {frame/fps}
        intervals = list(self.plan['crop_intervals']) + list(self.plan['intentional_overlaps'])
        intervals += [i for o in self.objects.values() for i in o['observation_intervals']]
        intervals += self.plan['timeline']
        for interval in intervals:
            for key in ('start', 'end'):
                n = math.ceil(interval[key]*fps-1e-7)
                if frame <= n < frame+count:
                    times.add(n/fps)
        for index, checkpoint in enumerate(self.plan.get('geometry_checkpoints',[])):
            n=min(frame_at(checkpoint['time'],fps),max(0,frame_at(self.plan['duration'],fps)-1))
            if frame<=n<frame+count:
                oid=checkpoint['object_id']
                groups={g['id']:g['members'] for g in self.plan['groups']}
                members=groups.get(oid,[oid])
                parts=[objects[x]['box'] for x in members if x in objects]
                box=([min(b[0] for b in parts),max(b[1] for b in parts),
                      min(b[2] for b in parts),max(b[3] for b in parts)] if parts else None)
                item=dict(box=box) if box is not None else None
                if item is None or any(abs(a-b)>checkpoint['tolerance']
                                       for a,b in zip(item['box'],checkpoint['box'])):
                    self.issue('GEOMETRY_CHECKPOINT',members,n/fps,
                        'Measured visible bounds '+str(item['box'] if item else None)+
                        ' differ from planned '+str(checkpoint['box'])+
                        ' at planned time '+str(checkpoint['time'])+' (frame '+str(n)+')',
                        'timeline.geometry_checkpoints', occurrence=index)
        for time in sorted(times):
            self._check(objects, time)

    def _check(self, objects, time):
        bounds = self.telemetry.frame_profile['safe_bounds']
        for oid, expected in self.objects.items():
            if expected['layout_role'] == 'focal' and any(system.active(i,time) for i in expected['observation_intervals']) and oid not in objects:
                self.issue('FOCAL_NOT_VISIBLE', [oid], time, 'Focal absent during required observation', 'object_roles.focal')
        for oid, item in objects.items():
            expected = self.objects.get(oid)
            if expected is None or item.get('kind', item['role']) != expected['kind'] or item.get('layout_role') != expected['layout_role']:
                self.issue('OBJECT_METADATA_MISMATCH', [oid], time, 'Unplanned object or mismatched kind/layout_role', 'object_metadata')
                continue
            a = item['box']
            edges = system.crop_edges(self.plan, oid, time)
            violations = [edge for edge, wrong in [
                ('left', a[0] < bounds[0]-.02), ('right', a[1] > bounds[1]+.02),
                ('bottom', a[2] < bounds[2]-.02), ('top', a[3] > bounds[3]+.02)] if wrong and edge not in edges]
            if violations:
                self.issue('SAFE_AREA', [oid], time, 'Rendered object leaves the safe area at '+', '.join(violations), 'render.safe_bounds')
            if item.get('font_size', 100) < self.telemetry.frame_profile['min_font_size']-.1:
                self.issue('UNREADABLE_FONT', [oid], time, 'Effective font below contract minimum', 'render.min_font_size')
            if expected['layout_role'] == 'hud':
                h = self.plan['hud_region']
                if len(h)!=4 or a[0] < h[0]-.02 or a[1] > h[1]+.02 or a[2] < h[2]-.02 or a[3] > h[3]+.02:
                    self.issue('HUD_REGION', [oid], time, 'HUD leaves its declared upper region', 'layout_policy.hud')
                center = item.get('center', [(a[0]+a[1])/2, (a[2]+a[3])/2])
                if any(abs(x-y) > .02 for x,y in zip(center,expected['anchor'])):
                    self.issue('HUD_ANCHOR', [oid], time, 'HUD moved from its fixed anchor', 'layout_policy.hud')
                pose=item.get('pose_signature')
                pose_key=oid
                if pose and not item.get('content_transform') and self._changed(pose,self.hud_poses.setdefault(pose_key,pose)):
                    self.issue('HUD_TRANSFORM',[oid],time,'HUD was scaled or rotated','layout_policy.hud')
                signature = item.get('rigid_signature')
                value = item.get('font_size') if expected['kind'] in ('text','formula') else signature
                initial = self.hud_baselines.setdefault(oid, value)
                if value is not None and initial is not None:
                    changed = abs(value-initial) > .1 if isinstance(value,(int,float)) else self._changed(value,initial)
                    if changed:
                        self.issue('HUD_SCALE', [oid], time, 'HUD scaled or rotated with scene geometry', 'layout_policy.hud')
            groups = {g['id']:g['members'] for g in self.plan['groups']}
            for event in self.plan['timeline']:
                targets = {x for target in event['object_ids'] for x in groups.get(target,[target])}
                if oid in targets and event['operation'] in ('move','rotate') and system.active(event,time):
                    parts=item.get('rigid_parts')
                    if parts is None:
                        # Older snapshots do not provide per-piece evidence.
                        self.candidate([oid],time,'No per-piece material measurements; inspect rigid motion in the video')
                    elif not parts:
                        self.candidate([oid],time,'No visible filled material pieces can be measured; inspect motion in the video')
                    else:
                        if len(parts)>1:
                            self.candidate([oid],time,'Composite group measured by filled paths; verify which paths are real material pieces')
                        key=(oid,event['id'])
                        previous=self.rigid_memberships.setdefault(key,set(parts))
                        if previous != set(parts):
                            self.candidate([oid],time,'Visible material membership changed; inspect piece identity and continuity')
                        for part_id,metric in parts.items():
                            baseline=self.rigid_baselines.setdefault((oid,event['id'],part_id),metric)
                            if baseline['point_count'] != metric['point_count']:
                                self.candidate([oid],time,'Material path sampling changed; inspect geometry before deciding if a piece deformed')
                                continue
                            if self._changed([baseline['inertia'],baseline['area']],[metric['inertia'],metric['area']]):
                                self.issue('RIGID_PIECE_CHANGED',[oid],time,
                                    'Measured material '+part_id+' changed shape/area during move or rotation',
                                    'math_policy.undeclared_geometry_changes',occurrence=part_id)
            # Crop does not exempt the reserved caption strip. A bbox intersection
            # is sent for visual verification, rather than assuming visible ink.
            if a[2] < bounds[2]-.02:
                self.candidate([oid],time,'Inspect visible paths in the reserved caption region; crop is not a caption exemption')
        visible = list(objects.items())
        for i,(aid,a) in enumerate(visible):
            for bid,b in visible[i+1:]:
                x,y = a['box'],b['box']
                if min(x[1],y[1])-max(x[0],y[0]) <= .02 or min(x[3],y[3])-max(x[2],y[2]) <= .02:
                    continue
                # Even approved pairs remain subject to readability/occlusion.
                permitted = system.overlap_allowed(self.plan,aid,bid,time)
                for front_id,front,back_id,back in [(aid,a,bid,b),(bid,b,aid,a)]:
                    f,z = front['box'],back['box']
                    protected = self.objects.get(back_id,{}).get('layout_role') in ('hud','focal')
                    if (protected and front.get('opaque_rectangle') and front.get('draw_order',0) > back.get('draw_order',0)
                            and f[0] <= z[0] and f[1] >= z[1] and f[2] <= z[2] and f[3] >= z[3]):
                        self.issue('PROTECTED_OBJECT_OCCLUDED',[front_id,back_id],time,
                            'Opaque foreground rectangle covers HUD/focal despite crop or overlap permission','layout_policy.overlap')
                self.candidate([aid,bid],time,
                    'Inspect readability/occlusion of approved overlap' if permitted else
                    'Possible rendered geometry overlap without approval at this time; inspect actual paths')

    def check_content_target(self, oid, target, time):
        # Rebuild the target's untransformed glyphs. A different character outline
        # is legitimate; a rotated/stretched target is still a contract error.
        from manim import Text
        import numpy as np
        if not isinstance(target,Text):
            self.issue('HUD_CONTENT_UNVERIFIED',[oid],time,
                'Content replacement has no canonical text geometry evidence','layout_policy.hud')
            return
        size=float(target._font_size)
        canonical=Text(target.original_text,font=target.font,font_size=size,
            slant=target.slant,weight=target.weight,
            line_spacing=(target.line_spacing/size-1),
            t2f=target.t2f,t2s=target.t2s,t2w=target.t2w,
            disable_ligatures=target.disable_ligatures,tab_width=target.tab_width)
        def points(m):
            a=np.concatenate([p.points[:,:2] for p in m.get_family() if p.has_points()])
            return a-a.mean(axis=0)
        a,b=points(target),points(canonical)
        if a.shape!=b.shape or not np.allclose(a,b,atol=.002,rtol=.002):
            self.issue('HUD_TRANSFORM',[oid],time,
                'Replacement text target is scaled, rotated or deformed','layout_policy.hud')

    @staticmethod
    def _changed(a,b):
        return len(a) != len(b) or any(abs(x-y) > max(.001, abs(y)*.002) for x,y in zip(a,b))

    def event(self, event):
        groups = {g['id']:g['members'] for g in self.plan['groups']}
        start, end = event['start_frame']/self.telemetry.fps, (event['end_frame']+1)/self.telemetry.fps
        tolerance = self.telemetry.frame_profile['duration_tolerance_frames']/self.telemetry.fps
        for animation in event['animations']:
            for oid in animation['object_ids']:
                phase = ('ghost' if animation['type']=='FadeOut' else
                         'counter' if animation.get('target_text') is not None else 'geometry')
                rules = []
                for e in self.plan['timeline']:
                    members = {x for target in e['object_ids'] for x in groups.get(target,[target])}
                    if oid in members and e['phase']==phase:
                        rules.append(e)
                if rules and not any(start >= e['start']-tolerance and end <= e['end']+tolerance for e in rules):
                    self.issue('TIMELINE_MISMATCH',[oid],start,'Actual animation runs outside its declared sequential phase','timeline')
                for region in {e['region'] for e in rules}:
                    for previous in self.phase_events:
                        if (previous['region']==region and previous['phase']!=phase
                                and max(start,previous['start']) < min(end,previous['end'])-tolerance):
                            self.issue('PHASE_OVERLAP',[previous['object_id'],oid],start,
                                'Measured ghost/geometry/counter phases overlap in the same region','timeline')
                    entry=dict(region=region,phase=phase,start=start,end=end,object_id=oid)
                    if entry not in self.phase_events:
                        self.phase_events.append(entry)
