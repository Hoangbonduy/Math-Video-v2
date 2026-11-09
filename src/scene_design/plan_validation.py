"""Three planning gates; approved review criteria are assembled by Python."""
import copy
import math
from src.shared._workflow_store import WorkflowError
from src.scene_design import scene_contract as contract, scene_references

POLICY_VERSION = 1
INITIAL = "Initial state matches the approved inherited state."
END = "End state matches the approved script."
CONTINUITY = "Rendered previous last frame matches current first frame."


def fail(message):
    raise WorkflowError("INVALID_SCENE_DESIGN", message)


def planner_schema(bundle):
    from src.scene_design import system_contract as system
    schema = system.plan_schema(contract.STORY_SCHEMA, scene_references.RECIPES, bundle)
    for key in ("geometry_checkpoints", "reveal_checks", "criterion_rules", "illusion_spec"):
        schema["properties"].pop(key)
    beat = schema["properties"]["beats"]["items"]
    for key in ("criteria", "required_capabilities"):
        beat["properties"].pop(key)
    beat["required"] = list(beat["properties"])
    schema["required"] = list(schema["properties"])
    return schema


def _shape(plan, bundle):
    from src.scene_design import system_contract as system
    result = copy.deepcopy(plan)
    result.pop("planning_policy_version", None)
    # AI-supplied rule mappings are discarded; Python owns this derived data.
    result["criterion_rules"] = []
    defaults = dict(hud_region=[], groups=[], crop_intervals=[], intentional_overlaps=[],
        geometry_checkpoints=[], reveal_checks=[], criterion_rules=[],
        illusion_spec=dict(object_ids=[], start=0, end=0, expected_discrepancy="",
            preserved_invariants=[], reveal_policy="", approval_quote=""))
    for key, value in defaults.items():
        result.setdefault(key, value)
    for beat in (result.get("beats") if isinstance(result.get("beats"), list) else []):
        if isinstance(beat, dict):
            beat.setdefault("criteria", [])
            beat.setdefault("required_capabilities", [])
    for obj in (result.get("objects") if isinstance(result.get("objects"), list) else []):
        if isinstance(obj, dict):
            obj.setdefault("anchor", [])
            obj.setdefault("observation_intervals", [])
    schema = system.plan_schema(contract.STORY_SCHEMA, scene_references.RECIPES, bundle)
    schema["properties"]["beats"]["items"]["properties"]["criteria"].update(minItems=0, maxItems=60)
    schema["properties"]["criterion_rules"]["minItems"] = 0
    contract.structure(result, schema, "visual_plan")
    return result


def validate_metadata(plan, context, bundle):
    """Gate 3: identities and bounded times, with no layout/prose verdict."""
    from src.scene_design import system_contract as system
    system.assert_reference(plan, bundle)
    if plan["contract_conflict"] or plan["conflict_reason"].strip():
        system.fail(plan["conflict_reason"] or "Planner reported incompatible requirements")
    duration = plan["duration"]
    if duration <= 0:
        fail("Scene duration must be positive")
    def unique(items, label):
        ids = [item["id"] for item in items]
        if len(ids) != len(set(ids)):
            fail(label + " IDs must be unique")
        return set(ids)
    objects = unique(plan["objects"], "Object")
    groups = unique(plan["groups"], "Group")
    unique(plan["beats"], "Beat")
    unique(plan["timeline"], "Timeline")
    if objects & groups:
        fail("Object and group IDs must not collide")
    def refs(values, allowed):
        if len(values) != len(set(values)) or not set(values) <= allowed:
            fail("Unknown/duplicate object reference: " + repr(values))
    def time(value, path):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= duration:
            fail(path + " must be within scene duration")
    def interval(item, path):
        time(item["start"], path + ".start")
        time(item["end"], path + ".end")
        if item["start"] > item["end"]:
            fail(path + ": start must not exceed end")
    for group in plan["groups"]:
        refs(group["members"], objects)
    for beat in plan["beats"]:
        interval(beat, "beats[" + beat["id"] + "]")
    for obj in plan["objects"]:
        for row in obj["observation_intervals"]:
            interval(row, "observation_intervals")
    for event in plan["timeline"]:
        refs(event["object_ids"], objects | groups)
        interval(event, "timeline[" + event["id"] + "]")
    for row in plan["crop_intervals"]:
        refs(row["object_ids"], objects)
        refs(row["focal_ids"], objects)
        refs([row["group_id"]], groups)
        interval(row, "crop_intervals")
    for row in plan["intentional_overlaps"]:
        refs(row["object_ids"], objects)
        interval(row, "intentional_overlaps")
    for row in plan["geometry_checkpoints"]:
        refs([row["object_id"]], objects | groups)
        time(row["time"], "geometry_checkpoints.time")
    refs(plan["illusion_spec"]["object_ids"], objects | groups)
    interval(plan["illusion_spec"], "illusion_spec")
    return plan


def validate(plan, context):
    """Gate 1: data/script. Gate 2: lookup catalog. Gate 3: IDs/times."""
    from src.scene_design import system_contract as system
    bundle = context.get("system_contract") or system.load()
    if not isinstance(plan, dict):
        fail("Visual plan must be a JSON object")
    shaped = _shape(plan, bundle)
    scene, seconds = context["scene"], context["target_seconds"]
    if (shaped["scene_id"] != scene["scene_id"] or shaped["narration"] != scene["narration"]
            or abs(shaped["duration"] - seconds) > 1e-6):
        fail("Plan must preserve approved scene_id, narration and target duration")
    parts = " ".join(beat["narration_excerpt"] for beat in shaped["beats"])
    if " ".join(parts.split()) != " ".join(scene["narration"].split()):
        fail("Beat excerpts must preserve the approved narration")
    scene_references.validate_request(shaped["required_apis"], shaped["recipe_ids"])
    validate_metadata(shaped, context, bundle)
    return plan


def prepare(plan, context):
    """Copy approved criteria and generate rule mappings; never rewrite script files."""
    from src.scene_design import system_contract as system
    from src.scene_design.script_visuals import with_visual_handoff
    context = with_visual_handoff(context)
    validate(plan, context)
    bundle = context.get("system_contract") or system.load()
    result = _shape(plan, bundle)
    handoff = context.get("visual_handoff") or {}
    approved = handoff.get("scene", {}).get("acceptance_criteria", [])
    first, last = result["beats"][0], result["beats"][-1]
    for beat in result["beats"]:
        beat["criteria"] = list(dict.fromkeys(c for c in beat["criteria"] if c.strip()))
    known = {c for beat in result["beats"] for c in beat["criteria"]}
    for criterion in approved:
        if criterion not in known:
            first["criteria"].append(criterion)
            known.add(criterion)
    if INITIAL not in known:
        first["criteria"].append(INITIAL)
    if END not in known:
        last["criteria"].append(END)
    continuity = bool(handoff.get("previous_scene") or context.get("previous_scene_render"))
    if continuity and CONTINUITY not in known:
        first["criteria"].append(CONTINUITY)
    special = {INITIAL: "initial_state", END: "end_state"}
    if continuity:
        special[CONTINUITY] = "cross_scene_continuity"
    result["criterion_rules"] = [
        dict(beat_id=beat["id"], criterion=c, check=special.get(c, "content"),
             condition="verified_previous_frame" if special.get(c) == "cross_scene_continuity" else "always")
        for beat in result["beats"] for c in beat["criteria"]]
    # Missing visibility metadata is derived from declared appear/hide events.
    groups = {g["id"]: g["members"] for g in result["groups"]}
    for obj in result["objects"]:
        if obj["layout_role"] != "focal" or obj["observation_intervals"]:
            continue
        events = sorted((e for e in result["timeline"]
            if obj["id"] in {x for target in e["object_ids"] for x in groups.get(target, [target])}),
            key=lambda e: (e["start"], e["end"]))
        visible = None if any(e["operation"] == "appear" for e in events) else 0
        spans = []
        for event in events:
            if event["operation"] == "appear" and visible is None:
                visible = event["start"]
            elif event["operation"] == "hide" and visible is not None:
                if event["start"] > visible:
                    spans.append(dict(start=visible, end=event["start"]))
                visible = None
        if visible is not None and result["duration"] > visible:
            spans.append(dict(start=visible, end=result["duration"]))
        obj["observation_intervals"] = spans
    result["planning_policy_version"] = POLICY_VERSION
    validate(result, context)
    return result


def post_render_checks(plan, bundle):
    """Quality findings after a real movie exists; no lexical/prose gate."""
    from src.scene_design import system_contract as system
    issues = []
    def issue(code, ids, time, problem, rule):
        issues.append(dict(code=code, owner="planner", category="meaning", time=time,
            object_ids=list(ids), problem=problem, evidence=problem, rule=rule,
            fix="Correct layout metadata or code after inspecting the rendered draft"))
    objects = {o["id"]: o for o in plan["objects"]}
    groups = {g["id"]: g["members"] for g in plan["groups"]}
    bounds = system.profile(bundle)["safe_bounds"]
    hud = plan["hud_region"]
    valid_hud = (len(hud) == 4 and bounds[0] <= hud[0] < hud[1] <= bounds[1]
                 and 0 <= hud[2] < hud[3] <= bounds[3])
    for obj in objects.values():
        oid = obj["id"]
        if obj["layout_role"] == "hud":
            anchor = obj["anchor"]
            if not valid_hud or len(anchor) != 2 or not (hud[0] <= anchor[0] <= hud[1] and hud[2] <= anchor[1] <= hud[3]):
                issue("HUD_METADATA", [oid], 0, "HUD needs a fixed anchor in its upper safe region", "layout_policy.hud")
        if obj["kind"] in ("text", "formula") and obj["layout_role"] == "cropped_context":
            issue("READABLE_CROP", [oid], 0, "Text/formula cannot use a crop exemption", "layout_policy.crop")
        for row in obj["observation_intervals"]:
            if row["start"] == row["end"]:
                issue("OBSERVATION_INTERVAL", [oid], row["start"], "Observation needs positive duration", "object_roles.focal")
    for row in plan["crop_intervals"]:
        members = groups[row["group_id"]]
        if (not row["reason"].strip() or row["scale_factor"] <= 1 or row["start"] == row["end"]
                or not set(row["object_ids"] + row["focal_ids"]) <= set(members)
                or any(objects[x]["layout_role"] == "hud" for x in members)
                or any(objects[x]["layout_role"] != "cropped_context" for x in row["object_ids"])
                or any(objects[x]["layout_role"] != "focal" for x in row["focal_ids"])):
            issue("CROP_METADATA", members, row["start"], "Crop scope/roles must match the rendered group and observations", "layout_policy.crop")
    for row in plan["intentional_overlaps"]:
        if not row["reason"].strip() or row["start"] == row["end"]:
            issue("OVERLAP_METADATA", row["object_ids"], row["start"], "Overlap needs a reason and positive duration", "layout_policy.overlap")
    for row in plan["timeline"]:
        if row["start"] == row["end"] and row["operation"] not in ("appear", "hide", "update"):
            ids = [x for target in row["object_ids"] for x in groups.get(target, [target])]
            issue("TIMELINE_DURATION", ids, row["start"], "Motion/hold needs positive duration", "timeline")
    for row in plan.get("geometry_checkpoints", []):
        box = row["box"]
        text = objects.get(row["object_id"], {}).get("kind") in ("text", "formula")
        if (not 0 < row["tolerance"] <= .05 or box[0] > box[1] or box[2] > box[3]
                or (box[0] == box[1] and box[2] == box[3])
                or (text and (box[0] == box[1] or box[2] == box[3]))):
            ids = groups.get(row["object_id"], [row["object_id"]])
            issue("CHECKPOINT_METADATA", ids, row["time"], "Optional checkpoint has invalid bounds/tolerance", "geometry_checkpoints")
    return issues
