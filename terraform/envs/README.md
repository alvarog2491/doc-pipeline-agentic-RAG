# envs/

`<env>.tfvars` selects the environment. The remote-state location is passed separately because the
bucket name contains the AWS account id, which no file in the repository can know:

```bash
terraform init -reconfigure \
  -backend-config="bucket=doc-pipeline-tfstate-<account-id>" \
  -backend-config="key=<env>/terraform.tfstate" \
  -backend-config="region=<region>" \
  -backend-config="use_lockfile=true"
terraform plan -var-file=envs/<env>.tfvars
```

`docpipe deploy ...` and the GitHub workflows run exactly this. Preview environments use `-var env=pr-<n>`
with their own state key (`pr-<n>/terraform.tfstate`).
