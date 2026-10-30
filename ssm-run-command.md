[目次へ戻る](README.md) / [SSM Agent の役割とフットプリント](ssm-agent.md)

# SSM Run Command

## 用語

| 用語 | 意味 |
| --- | --- |
| 管理対象インスタンス | SSM Agent が動き、Systems Manager に登録されている EC2 など。コマンドを受けて実行する側 |
| コマンドドキュメント | 実行する処理の定義。シェルを流すだけなら AWS 提供の `AWS-RunShellScript`（Linux）や `AWS-RunPowerShellScript`（Windows）を使う |
| コマンド | `send-command` 1 回分の実行依頼。コマンド ID を持つ |
| コマンド呼び出し | 1 つのコマンドのうち、管理対象インスタンス 1 台分の実行。状態と出力は台ごとに残る |
| 関連付け | State Manager の設定。どのドキュメントを、どの管理対象インスタンスに、どのスケジュールで実行するかを決める |

## 概要

Run Command は、AWS Systems Manager の機能の 1 つ。管理対象インスタンスに、SSH で入らずにコマンドやスクリプトを実行させる。実行するのは各インスタンスの SSM Agent で、Agent が Systems Manager のエンドポイントから指示を取りにいく。そのため、インスタンス側で受信ポートを開ける必要はない。

| 観点 | SSH | Run Command |
| --- | --- | --- |
| 受信ポート | 22 番を開ける | 不要（Agent からの送信だけ） |
| 認証 | 鍵やユーザーをインスタンスごとに管理する | IAM で、誰がどのドキュメントをどのインスタンスに実行できるかを決める |
| 多数台への実行 | 自前で並べる | タグなどで対象を指定し、同時実行数とエラーの上限を決めて流す |
| 記録 | 自前で残す | 実行の依頼は CloudTrail に、実行結果はコマンド呼び出しとして残る |

押さえる点:

- **対象の指定**: インスタンス ID の列挙のほか、タグ（`tag:Role=app` など）やリソースグループで指定できる。
- **同時実行数とエラーの上限**: `--max-concurrency` で同時に実行する台数を、`--max-errors` で失敗が何台を超えたら残りを止めるかを決める。30 台に一斉に流して全台を壊す、といった事故を防ぐ。
- **出力の行き先**: API で取れる標準出力は先頭 24,000 文字まで。全文を残すなら S3 か CloudWatch Logs に出す。出力を書き込むのはインスタンスなので、その権限はインスタンスプロファイルに付ける。

## 前提条件

1. **SSM Agent が動いていること**: Amazon Linux や Ubuntu などの AWS 提供 AMI には、最初から入っている。
2. **インスタンスプロファイル**: マネージドポリシー `AmazonSSMManagedInstanceCore` を付けた IAM ロールを、インスタンスに付ける。出力を S3 や CloudWatch Logs に出す場合は、その書き込み権限も足す。
3. **通信経路**: Agent が Systems Manager のエンドポイントに HTTPS で届くこと。プライベートサブネットでは、NAT ゲートウェイか、VPC エンドポイントの `ssm` と `ssmmessages` を用意する。SSM Agent 3.3.40.0 より前の版は `ec2messages` も使う。[AWS 公式：VPC エンドポイントを使用した Systems Manager の設定](https://docs.aws.amazon.com/systems-manager/latest/userguide/setup-create-vpc.html)
4. **実行する人の権限**: `ssm:SendCommand` を、使うドキュメントと対象のインスタンスに絞って許可する。

管理対象インスタンスとして登録されているかは、次のコマンドで確かめる。`Ping` が `Online` なら、コマンドを受けられる。

```bash
aws ssm describe-instance-information \
  --query 'InstanceInformationList[].{Id:InstanceId,Ping:PingStatus,Agent:AgentVersion,Platform:PlatformName}' \
  --output table
```

## 簡単な実行方法

タグ `Role=app` の付いた管理対象インスタンスに、10 台ずつシェルのコマンドを流す例。1 台でも失敗したら残りへの実行を止める。出力は CloudWatch Logs に残す。

```bash
aws ssm send-command \
  --document-name AWS-RunShellScript \
  --targets Key=tag:Role,Values=app \
  --parameters 'commands=["df -h","systemctl is-active nginx"]' \
  --max-concurrency 10 \
  --max-errors 1 \
  --comment "disk and nginx check" \
  --cloud-watch-output-config CloudWatchOutputEnabled=true,CloudWatchLogGroupName=/ssm/run-command \
  --query Command.CommandId --output text
```

返ってきたコマンド ID で、台ごとの結果（コマンド呼び出し）を確かめる。

```bash
aws ssm list-command-invocations \
  --command-id <コマンド ID> \
  --details \
  --query 'CommandInvocations[].{Instance:InstanceId,Status:Status,Output:CommandPlugins[0].Output}'
```

1 台分だけを見るなら `aws ssm get-command-invocation --command-id <コマンド ID> --instance-id <インスタンス ID>` を使う。

## 定期実行

Run Command 自体にはスケジュールの設定がない。ただし、同じ Systems Manager の中に定期実行の仕組みがあるので、別のサービスを用意しなくても定期実行できる。

### 仕組みの選び方

| 仕組み | 置き場所 | スケジュール | 向いている用途 |
| --- | --- | --- | --- |
| **State Manager の関連付け** | Systems Manager の機能 | cron 式か rate 式。cron は **UTC** で評価される。間隔は 30 分以上 | 同じコマンドを決まった周期で流し続ける。あとから条件に合うようになったインスタンスにも適用される |
| メンテナンスウィンドウ | Systems Manager の機能 | cron 式。タイムゾーンを指定できる。作業してよい時間帯の長さと締め切りを決める | パッチ適用など、止めてよい時間帯の中で終わらせたい作業 |
| EventBridge Scheduler | 別のサービス | cron 式・rate 式・1 回だけ。タイムゾーンを指定できる。1 分単位 | 30 分より短い間隔、1 回だけの予約、ほかのサービスの定期実行と一か所で管理したい場合 |

「決まった時刻にコマンドを流す」だけなら、State Manager の関連付けが手軽。以下ではまずこれを使う。

### State Manager での設定

毎日 日本時間 2:00 に、上と同じコマンドを流す例。cron 式は UTC なので、日本時間 2:00 は前日の UTC 17:00 になる。

```bash
aws ssm create-association \
  --association-name app-disk-check \
  --name AWS-RunShellScript \
  --targets Key=tag:Role,Values=app \
  --parameters 'commands=["df -h","systemctl is-active nginx"]' \
  --schedule-expression 'cron(0 17 ? * * *)' \
  --apply-only-at-cron-interval \
  --max-concurrency 10 \
  --max-errors 1 \
  --output-location '{"S3Location":{"OutputS3BucketName":"my-ssm-output","OutputS3KeyPrefix":"app-disk-check"}}'
```

- `--apply-only-at-cron-interval` を付けないと、関連付けを作った直後にも 1 回実行される。設定を変更したときも同じ。
- cron 式は 6 項目（分 時 日 月 曜日 年）で、日と曜日のどちらかを `?` にする。

実行の履歴は次のコマンドで確かめる。

```bash
aws ssm list-associations --association-filter-list key=AssociationName,value=app-disk-check
aws ssm describe-association-executions --association-id <関連付け ID>
```

### EventBridge Scheduler での設定

30 分より短い間隔で流す場合や、日本時間のまま書きたい場合に使う。EventBridge Scheduler は、どの AWS API でも呼べる汎用のターゲット（ユニバーサルターゲット）として、Run Command の `SendCommand` を呼ぶ。

スケジューラが引き受ける IAM ロールを用意する。信頼ポリシーで `scheduler.amazonaws.com` を許可し、権限は `ssm:SendCommand` をドキュメント `AWS-RunShellScript` と対象のインスタンスに限る。そのうえでスケジュールを作る。

```bash
aws scheduler create-schedule \
  --name app-disk-check \
  --schedule-expression 'cron(0 2 * * ? *)' \
  --schedule-expression-timezone Asia/Tokyo \
  --flexible-time-window Mode=OFF \
  --target '{
    "Arn": "arn:aws:scheduler:::aws-sdk:ssm:sendCommand",
    "RoleArn": "arn:aws:iam::111122223333:role/app-disk-check-scheduler",
    "Input": "{\"DocumentName\":\"AWS-RunShellScript\",\"Targets\":[{\"Key\":\"tag:Role\",\"Values\":[\"app\"]}],\"Parameters\":{\"commands\":[\"df -h\"]},\"MaxConcurrency\":\"10\",\"MaxErrors\":\"1\"}"
  }'
```

`Input` には、`SendCommand` API のリクエストを JSON の文字列で書く。結果は、State Manager の場合と違って関連付けの履歴には残らないので、Run Command のコマンド履歴か、出力先で確かめる。
