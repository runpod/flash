from runpod_flash.core.resources.gpu import GpuGroup, GpuType, POOLS_TO_TYPES


class TestGpuIdsImports:
    def test_imports_work(self):
        # highlights the import crash that used to happen from type annotations
        assert GpuGroup is not None
        assert GpuType is not None


class TestGpuIdsBehavior:
    def test_to_gpu_ids_str_groups_only_contains_pool_ids(self):
        gpu_ids = GpuGroup.to_gpu_ids_str([GpuGroup.AMPERE_48, GpuGroup.AMPERE_24])
        # only pools should be present when selecting groups
        assert "AMPERE_48" in gpu_ids
        assert "AMPERE_24" in gpu_ids
        assert all(not token.startswith("-") for token in gpu_ids.split(",") if token)

    def test_from_gpu_ids_str_pool_only_returns_group(self):
        parsed = GpuGroup.from_gpu_ids_str("AMPERE_24")
        assert parsed == [GpuGroup.AMPERE_24]

    def test_gpu_type_is_gpu_type_checks_enum_values(self):
        assert GpuType.is_gpu_type("L4") is False
        assert GpuType.is_gpu_type("NVIDIA L4") is True

    def test_blackwell_groups_round_trip(self):
        gpu_ids = GpuGroup.to_gpu_ids_str([GpuGroup.BLACKWELL_96])
        assert "BLACKWELL_96" in gpu_ids
        parsed = GpuGroup.from_gpu_ids_str(gpu_ids)
        assert parsed == [GpuGroup.BLACKWELL_96]

        gpu_ids = GpuGroup.to_gpu_ids_str([GpuGroup.BLACKWELL_180])
        assert "BLACKWELL_180" in gpu_ids
        parsed = GpuGroup.from_gpu_ids_str(gpu_ids)
        assert parsed == [GpuGroup.BLACKWELL_180]

    def test_b200_type_maps_to_blackwell_180(self):
        gpu_ids = GpuGroup.to_gpu_ids_str([GpuType.B200])
        assert "BLACKWELL_180" in gpu_ids
        # b200 is the only type in BLACKWELL_180, so no negations needed
        # and from_gpu_ids_str returns the group
        parsed = GpuGroup.from_gpu_ids_str(gpu_ids)
        assert parsed == [GpuGroup.BLACKWELL_180]

    def test_rtx_pro_6000_type_maps_to_blackwell_96(self):
        gpu_ids = GpuGroup.to_gpu_ids_str(
            [GpuType.RTX_PRO_6000_BLACKWELL_SERVER_EDITION]
        )
        assert "BLACKWELL_96" in gpu_ids
        # other RTX PRO 6000 variants are negated
        parsed = GpuGroup.from_gpu_ids_str(gpu_ids)
        assert GpuType.RTX_PRO_6000_BLACKWELL_SERVER_EDITION in parsed

    def test_every_gpu_type_has_pool_mapping(self):
        all_mapped = set()
        for types in POOLS_TO_TYPES.values():
            all_mapped.update(types)
        for gpu_type in GpuType.all():
            assert gpu_type in all_mapped, f"{gpu_type.name} has no pool mapping"

    def test_deprecated_aliases_resolve_to_canonical(self):
        assert GpuType.NVIDIA_L4 is GpuType.L4
        assert GpuType.NVIDIA_A40 is GpuType.A40
        assert GpuType.NVIDIA_H200 is GpuType.H200
        assert GpuType.NVIDIA_GEFORCE_RTX_4090 is GpuType.GEFORCE_RTX_4090
