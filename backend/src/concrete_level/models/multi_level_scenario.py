from typing import Dict, Set, Union

from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from functional_level.metamodels.functional_scenario import FuncObject, FunctionalScenario
from logical_level.constraint_satisfaction.evaluation_cache import GeometricProperties
from logical_level.models.actor_variable import ActorVariable
from logical_level.models.logical_scenario import LogicalScenario
from logical_level.models.penalty import Penalty


class MultiLevelScenario:
    def __init__(
        self,
        concrete_scene: ConcreteScene,
        logical_scenario: LogicalScenario,
        functional_scenario: FunctionalScenario,
    ):
        self.concrete_scene = concrete_scene
        self.logical_scenario = logical_scenario
        self.functional_scenario = functional_scenario

        self.concrete_actor_map: Dict[int, ConcreteActor] = {actor.id: actor for actor in self.concrete_scene.actors}
        self.logical_actor_map: Dict[int, ActorVariable] = {actor.id: actor for actor in self.logical_scenario.actor_variables}
        self.functional_object_map: Dict[int, FuncObject] = {obj.id: obj for obj in self.functional_scenario.sorted_sea_objects}
        self.assignments = self.concrete_scene.assignments
        self.evaluation_cache = self.concrete_scene.evaluation_cache

    @property
    def penalty(self) -> Penalty:
        return self.logical_scenario.relation_constraint.evaluate_penalty(self.assignments)

    def to_concrete_actor(self, actor_or_obj: Union[ConcreteActor, FuncObject]) -> ConcreteActor:
        return self.concrete_actor_map[actor_or_obj.id]

    def to_variable(self, actor_or_obj: Union[ConcreteActor, FuncObject]) -> ActorVariable:
        return self.logical_actor_map[actor_or_obj.id]

    def get_geo_props(self, actor1: ConcreteActor, actor2: ConcreteVessel) -> GeometricProperties:
        return self.concrete_scene.get_geo_props(actor1, actor2)

    def may_collide(self, actor1: ConcreteActor, actor2: ConcreteVessel) -> bool:
        return self.concrete_scene.on_collision_course(actor1, actor2)

    def may_collide_anyone(self, vessel: ConcreteVessel) -> bool:
        for actor2 in self.concrete_actor_map.values():
            if vessel == actor2:
                continue
            if self.may_collide(actor2, vessel):
                return True
        return False

    @property
    def os_ts_pairs(self) -> Set[Relation]:
        os = self.concrete_scene.os
        return {Relation(os, vessel) for vessel in self.concrete_scene.ts_vessels}
