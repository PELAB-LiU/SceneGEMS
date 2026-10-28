"""EvalDataParser and TrajDataParser: loading models and tables from json, zip, tar.gz and pkl.gz files without dialogs."""

import gzip
import io
import json
import pickle
import tarfile
import zipfile

import pytest

from concrete_level.data_parser import DataParser, EvalDataParser, TrajDataParser
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.file_folder_opener import FileFolderOpener


class FakeOpener(FileFolderOpener):
    def __init__(self, files=(), dirs=(), save=None):
        self.files, self.dirs, self.save = list(files), list(dirs), save
        self.asked = []

    def ask_open_dirs(self, initialdir="."):
        self.asked.append(("dirs", initialdir))
        return self.dirs

    def ask_open_files(self, initialdir=".", filetypes=None):
        self.asked.append(("files", initialdir))
        return self.files

    def ask_save_file(self, initialdir=".", filetypes=None):
        self.asked.append(("save", initialdir))
        return self.save


def _eval(name="scenario", seed=1, **changes):
    return EvaluationData(algorithm_desc="ga", scenario_name=name, random_seed=seed, timestamp=f"t{seed}", **changes)


def _write_json(path, data):
    path.write_text(json.dumps(data.to_dict()))
    return str(path)


class TestEvalDataParser:
    def test_a_json_file_loads_as_a_model_that_remembers_its_path(self, tmp_path):
        file = _write_json(tmp_path / "a.json", _eval())
        parser = EvalDataParser(FakeOpener())
        model = parser.load_model_from_file(file)
        assert (model.scenario_name, model.random_seed, model.path) == ("scenario", 1, file)
        assert parser.load_dict_from_file(file)["path"] == file

    def test_models_from_the_files_the_user_picks(self, tmp_path):
        files = [_write_json(tmp_path / "a.json", _eval(seed=1)), _write_json(tmp_path / "b.json", _eval(seed=2))]
        opener = FakeOpener(files=files)
        models = EvalDataParser(opener).load_data_models()
        assert [model.random_seed for model in models] == [1, 2] and [model.path for model in models] == files
        assert opener.asked[0][0] == "files"

    def test_models_from_the_json_files_of_the_picked_folders_including_subfolders(self, tmp_path):
        (tmp_path / "sub").mkdir()
        _write_json(tmp_path / "a.json", _eval(seed=1))
        _write_json(tmp_path / "sub" / "b.json", _eval(seed=2))
        (tmp_path / "note.txt").write_text("not data")
        models = EvalDataParser(FakeOpener(dirs=[str(tmp_path)])).load_dirs_merged_as_models()
        assert sorted(model.random_seed for model in models) == [1, 2]

    def test_a_zip_loads_only_its_json_members(self, tmp_path):
        archive = tmp_path / "data.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("one.json", json.dumps(_eval(seed=1).to_dict()))
            zipped.writestr("readme.txt", "skip me")
        models = EvalDataParser(FakeOpener()).load_zip_eval_data(str(archive))
        assert [(model.random_seed, model.path) for model in models] == [(1, "one.json")]

    def test_a_tar_gz_loads_only_its_json_files(self, tmp_path):
        archive = tmp_path / "data.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name, content in (("a.json", json.dumps(_eval(seed=3).to_dict())), ("b.txt", "skip me")):
                raw = content.encode()
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
        models = EvalDataParser(FakeOpener()).load_tar_eval_data(str(archive))
        assert [(model.random_seed, model.path) for model in models] == [(3, "a.json")]

    def test_a_dumped_gz_loads_back_through_the_picked_file(self, tmp_path):
        target = tmp_path / "all.pkl.gz"
        opener = FakeOpener(save=str(target))
        parser = EvalDataParser(opener)
        parser.dump_eval_datas_to_gz([_eval(seed=1), _eval(seed=2)])
        assert opener.asked == [("save", parser.dir)]
        assert [model.random_seed for model in parser.load_pkl_gzip_compressed_eval_data(str(target))] == [1, 2]
        picked = EvalDataParser(FakeOpener(files=[str(target)]))
        assert len(picked.load_pkl_gzip_compressed_eval_data()) == 2

    def test_dumping_to_a_given_file_asks_for_nothing(self, tmp_path):
        opener = FakeOpener()
        EvalDataParser(opener).dump_eval_datas_to_gz([_eval()], file=str(tmp_path / "x.gz"))
        with gzip.open(tmp_path / "x.gz", "rb") as stored:
            assert len(pickle.load(stored)) == 1
        assert opener.asked == []

    def test_cancelling_the_save_dialog_ends_the_program(self):
        with pytest.raises(SystemExit):
            EvalDataParser(FakeOpener(save=None)).dump_eval_datas_to_gz([_eval()])

    def test_the_table_has_a_row_per_file_and_skips_failed_ones_without_a_best_scene(self, tmp_path):
        good = _write_json(tmp_path / "good.json", _eval(seed=1))
        failed = _write_json(tmp_path / "failed.json", _eval(seed=2, error_message="boom"))
        table = EvalDataParser(FakeOpener()).load_df_from_files([good, failed])
        assert list(table["random_seed"]) == [1]
        assert list(table.columns) == EvalDataParser.EVAL_DATA_COLUMN_NAMES

    def test_dirs_merged_returns_the_table_and_the_folders(self, tmp_path):
        _write_json(tmp_path / "a.json", _eval(seed=4))
        table, dirs = EvalDataParser(FakeOpener()).load_dirs_merged([str(tmp_path)])
        assert list(table["random_seed"]) == [4] and dirs == [str(tmp_path)]

    def test_dirs_merged_without_folders_asks_the_user(self, tmp_path):
        _write_json(tmp_path / "a.json", _eval(seed=4))
        opener = FakeOpener(dirs=[str(tmp_path)])
        table, dirs = EvalDataParser(opener).load_dirs_merged()
        assert opener.asked[0][0] == "dirs" and len(table) == 1 and dirs == [str(tmp_path)]


class TestTrajDataParser:
    def _trajectory_file(self, tmp_path, **changes):
        fields = {column: None for column in DataParser.TRAJ_COLUMN_NAMES}
        fields.update({"error_message": None, "timestamp": "t", "best_scene": None, "algorithm_desc": "rrt", "config_name": "c", "random_seed": 3})
        fields.update(changes)
        file = tmp_path / "traj.json"
        file.write_text(json.dumps({key: value for key, value in fields.items() if key in {"algorithm_desc", "config_name", "random_seed", "timestamp", "error_message"}}))
        return str(file)

    def test_a_trajectory_file_loads_as_a_model_that_remembers_its_path(self, tmp_path):
        file = self._trajectory_file(tmp_path)
        parser = TrajDataParser(FakeOpener(files=[file]))
        [model] = parser.load_data_models()
        assert (model.config_name, model.random_seed, model.path) == ("c", 3, file)
        assert parser.load_dict_from_file(file)["path"] == file

    def test_the_parser_starts_in_the_rrt_folder(self):
        opener = FakeOpener()
        TrajDataParser(opener).load_data_models()
        assert opener.asked == [("files", DataParser.RRT_DIR)]
