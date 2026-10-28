"""EvalDataParser: loading models and tables from json and pkl.gz files without dialogs."""

import gzip
import json
import pickle

import pytest

from concrete_level.data_parser import EvalDataParser
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
