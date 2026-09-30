import pytest

from scripts.pipeline_tools import terraform
from scripts.pipeline_tools.commands import deploy as deploy_commands
from scripts.pipeline_tools.commands import docs
from scripts.pipeline_tools.config import Config
from scripts.pipeline_tools.ui import Failure


class _Aws:
    def account_id(self):
        return "123456789012"


class _Ctx:
    def __init__(self, env="dev", region="eu-central-1"):
        self.config = Config(env=env, region=region, profile="", image_tag="dev-me")
        self.aws = _Aws()

    def refuse_managed(self):
        if self.config.is_managed:
            raise Failure("managed")


def test_each_environment_gets_its_own_state_object():
    assert Config("prod", "r", "", "t").tf_state_key == "prod/terraform.tfstate"
    assert Config("pr-42", "r", "", "t").tf_state_key == "pr-42/terraform.tfstate"


def test_named_environments_use_their_tfvars_and_previews_pass_the_name(monkeypatch):
    monkeypatch.delenv("TF_STATE_BUCKET", raising=False)

    named = terraform.var_args(_Ctx("staging"), None)
    preview = terraform.var_args(_Ctx("pr-7"), None)

    assert named[0] == "-var-file=envs/staging.tfvars"
    assert preview[:2] == ["-var", "env=pr-7"]
    assert ["-var", "region=eu-central-1"] == named[1:3]


def test_blank_variables_are_omitted_so_module_defaults_apply():
    args = terraform.var_args(
        _Ctx(), {"agent_image_tag": "sha-1", "langfuse_base_url": ""}
    )

    assert "agent_image_tag=sha-1" in args
    assert not any("langfuse_base_url" in arg for arg in args)


def test_backend_config_targets_the_account_bucket_and_native_locking(monkeypatch):
    monkeypatch.delenv("TF_STATE_BUCKET", raising=False)

    args = terraform.backend_args(_Ctx("dev"))

    assert "-backend-config=bucket=doc-pipeline-tfstate-123456789012" in args
    assert "-backend-config=key=dev/terraform.tfstate" in args
    assert "-backend-config=use_lockfile=true" in args


def test_state_bucket_can_be_overridden(monkeypatch):
    monkeypatch.setenv("TF_STATE_BUCKET", "custom-bucket")

    assert terraform.state_bucket(_Ctx()) == "custom-bucket"


def test_managed_environments_cannot_be_deployed_or_destroyed_by_hand():
    for env in ("prod", "staging"):
        with pytest.raises(Failure):
            deploy_commands.deploy(_Ctx(env))
        with pytest.raises(Failure):
            deploy_commands.destroy(_Ctx(env), assume_yes=True)
        with pytest.raises(Failure):
            docs.upload(_Ctx(env), "x.pdf", wait=False)


def test_upload_rejects_non_pdf_paths(tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("hi")

    with pytest.raises(Failure, match="not a PDF"):
        docs.upload(_Ctx(), str(text), wait=False)
    with pytest.raises(Failure, match="not a PDF"):
        docs.upload(_Ctx(), str(tmp_path / "missing.pdf"), wait=False)


def test_upload_sends_the_chunking_choice_as_s3_object_metadata(tmp_path, monkeypatch):
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    uploads = []

    class _S3:
        def upload_file(self, filename, bucket, key, ExtraArgs):
            uploads.append((bucket, key, ExtraArgs))

    class _Client:
        def client(self, name):
            return _S3()

    ctx = _Ctx()
    ctx.aws = _Client()
    monkeypatch.setattr(docs.terraform, "output", lambda c, name: "docs-bucket")

    docs.upload(ctx, str(pdf), wait=False, chunking="fixed", max_tokens=200)
    docs.upload(ctx, str(pdf), wait=False)

    assert uploads[0] == (
        "docs-bucket",
        "uploads/deck.pdf",
        {
            "ContentType": "application/pdf",
            "Metadata": {"chunking": "fixed", "max-tokens": "200"},
        },
    )
    assert uploads[1][2] == {
        "ContentType": "application/pdf"
    }  # no override -> Bedrock default


def test_personal_dev_image_tags_are_unique_per_deploy_unless_pinned(monkeypatch):
    monkeypatch.delenv("IMAGE_TAG", raising=False)
    monkeypatch.setattr(
        "scripts.pipeline_tools.config.time.strftime", lambda fmt, t: "20260930120000"
    )

    assert Config.from_env().image_tag.endswith("-20260930120000")

    monkeypatch.setenv("IMAGE_TAG", "sha-abc")
    assert Config.from_env().image_tag == "sha-abc"
