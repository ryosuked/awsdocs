[目次へ戻る](README.md)

# 6. CodeBuild / CodeDeploy / CodePipeline / EC2 Image Builder

この章のサービスは、[5 章](05-cloudformation-iam.md)の CloudFormation で用意した環境の上で、アプリケーションのビルドとデプロイ、サーバーイメージの作成を繰り返し自動で行う。パイプラインやビルドプロジェクトの設定そのものも、CloudFormation で作る。

```mermaid
flowchart LR
    subgraph P[CodePipeline]
        direction LR
        S[Source] --> B[Build<br/>CodeBuild] --> A{承認} --> D[Deploy<br/>CodeDeploy・ECS など]
    end
    Repo[ソースリポジトリ<br/>GitHub など] -->|push| S
    D -->|アプリを配置| Env[EC2・Lambda・ECS]
    IB[EC2 Image Builder<br/>パイプライン] -->|AMI| Env
```

## CodeBuild

ソースコードのビルド、テスト、パッケージングを実行するマネージドなビルドサービス。ビルドサーバーを用意する必要がなく、使った時間だけ課金される。

**主な概念**

- **ビルドプロジェクト**: ソースの場所、ビルド環境（コンテナイメージ、コンピューティングのサイズ）、サービスロール、成果物の出力先を決める。
- **buildspec.yml**: リポジトリに置くビルド手順。`phases`（`install` → `pre_build` → `build` → `post_build`）、`artifacts`（成果物）、`cache`、`reports`（テスト結果）を書く。
- **ビルド環境**: AWS 提供の標準イメージか、ECR などの自作イメージ。Docker イメージをビルドすることもできる。
- **出力**: ログは CloudWatch Logs や S3 に、成果物は S3 や ECR に置く。

```yaml
# 例: buildspec.yml
version: 0.2
phases:
  install:
    runtime-versions:
      nodejs: 20
  build:
    commands:
      - npm ci
      - npm test
      - npm run build
artifacts:
  base-directory: dist
  files:
    - "**/*"
```

## CodeDeploy

ビルド済みのアプリケーションを、EC2（オンプレミスのサーバーを含む）、Lambda、ECS に配置するデプロイサービス。台数の多い環境でも、止めずに少しずつ入れ替え、失敗したら元に戻す。

**主な概念**

- **アプリケーションとデプロイグループ**: アプリケーションはデプロイ対象の名前の入れ物。デプロイグループは配置先の集まりで、EC2 ならタグや Auto Scaling グループで指定する。ALB を指定すると、入れ替え中のインスタンスを振り分けから外してくれる。
- **appspec.yml**: 成果物に含める配置の手順書。EC2 ではファイルのコピー先と、各段階で動かすスクリプトを書く。Lambda や ECS では切り替える版と、検証用の Lambda 関数を書く。
- **ライフサイクルフック（EC2）**: `ApplicationStop` → `BeforeInstall` → `AfterInstall` → `ApplicationStart` → `ValidateService` の順に、指定したスクリプトを実行する。
- **CodeDeploy エージェント**: EC2 で配置を行う常駐プログラム。インスタンスに入れておく（Lambda と ECS では不要）。
- **デプロイ方式**:

| 方式 | 内容 | 対象 |
| --- | --- | --- |
| インプレース | 今あるインスタンスの上でアプリを入れ替える | EC2 |
| ブルー/グリーン | 新しい環境を用意してから、通信を切り替える | EC2、Lambda、ECS |

- **デプロイ設定**: 一度に入れ替える範囲。EC2 では全台同時・半分ずつ・1 台ずつ。Lambda と ECS では、一部の通信だけ新しい版に流して様子を見るカナリア、一定の割合ずつ増やすリニアを選べる。
- **ロールバック**: デプロイの失敗や CloudWatch アラームをきっかけに、前の版へ自動で戻す。

```yaml
# 例: EC2 向けの appspec.yml
version: 0.0
os: linux
files:
  - source: /
    destination: /opt/app
hooks:
  ApplicationStop:
    - location: scripts/stop.sh
  AfterInstall:
    - location: scripts/install_deps.sh
  ApplicationStart:
    - location: scripts/start.sh
  ValidateService:
    - location: scripts/health_check.sh
      timeout: 300
```

## CodePipeline

ソースの変更からデプロイまでの流れ（パイプライン）を定義し、自動で順に実行する CI/CD のサービス。自分ではビルドやデプロイをせず、各段階を他のサービスに任せて取りまとめる。

**主な概念**

- **ステージとアクション**: パイプラインは複数のステージからなり、各ステージに 1 つ以上のアクションを置く。

| ステージの例 | アクションの提供元 |
| --- | --- |
| Source | GitHub / GitLab / Bitbucket（CodeConnections 経由）、S3、ECR |
| Build / Test | CodeBuild、Jenkins など |
| Approval | 手動承認（担当者が承認するまで止まる） |
| Deploy | CodeDeploy（EC2・Lambda）、ECS、S3、Elastic Beanstalk。インフラの変更もパイプラインで流す場合は CloudFormation |

- **アーティファクト**: ステージ間で受け渡す成果物。S3 のアーティファクトストアに置かれる。
- **パイプラインのタイプ**: V2 タイプではブランチやタグでの実行条件（トリガー）、パイプライン変数が使える。新しく作るなら V2 を選ぶ。

### 簡単な設定方法

GitHub の `main` ブランチへの push をきっかけに、CodeBuild でビルドするだけの最小構成を AWS CLI で作る。次の 4 つは先に用意しておく。

| 先に用意するもの | 内容 |
| --- | --- |
| CodeConnections の接続 | GitHub との接続。作った直後は「保留中」なので、コンソールで GitHub 側の承認を済ませて「利用可能」にする |
| CodeBuild のプロジェクト | 上の [CodeBuild](#codebuild) の節のもの。ソースの種類は `CODEPIPELINE` にする |
| アーティファクトストア | ステージ間で成果物を受け渡す S3 バケット |
| パイプラインのサービスロール | CodePipeline が引き受ける IAM ロール。接続の利用（`codeconnections:UseConnection`）、アーティファクトストアの読み書き、CodeBuild のビルドの開始と状態の取得を許可する |

パイプラインの定義を JSON で書く。

```json
{
  "pipeline": {
    "name": "my-app",
    "pipelineType": "V2",
    "roleArn": "arn:aws:iam::111122223333:role/my-app-pipeline",
    "artifactStore": { "type": "S3", "location": "my-app-pipeline-artifacts" },
    "stages": [
      {
        "name": "Source",
        "actions": [
          {
            "name": "Source",
            "actionTypeId": { "category": "Source", "owner": "AWS", "provider": "CodeStarSourceConnection", "version": "1" },
            "configuration": {
              "ConnectionArn": "arn:aws:codeconnections:ap-northeast-1:111122223333:connection/xxxxxxxx",
              "FullRepositoryId": "my-org/my-app",
              "BranchName": "main"
            },
            "outputArtifacts": [{ "name": "SourceOutput" }]
          }
        ]
      },
      {
        "name": "Build",
        "actions": [
          {
            "name": "Build",
            "actionTypeId": { "category": "Build", "owner": "AWS", "provider": "CodeBuild", "version": "1" },
            "configuration": { "ProjectName": "my-app-build" },
            "inputArtifacts": [{ "name": "SourceOutput" }],
            "outputArtifacts": [{ "name": "BuildOutput" }]
          }
        ]
      }
    ]
  }
}
```

```bash
aws codepipeline create-pipeline --cli-input-json file://pipeline.json
```

作った直後に 1 回実行され、そのあとは `main` への push のたびに実行される。手で実行するなら `aws codepipeline start-pipeline-execution --name my-app`、状態は `aws codepipeline get-pipeline-state --name my-app` で見る。デプロイまで流すなら、`stages` の後ろに Deploy ステージを足す。

### 定期実行（EventBridge Scheduler）

CodePipeline には、時刻をきっかけに実行する機能がない。上の V2 のトリガーが反応するのは、push やプルリクエストなどソース側の変化だけ。夜間のビルドのように時刻で動かすには、**EventBridge Scheduler** から CodePipeline の `StartPipelineExecution` を呼ばせる。実行されるパイプラインは、その時点の `main` の最新のコミットを取りにいく。

EventBridge Scheduler は CodePipeline をテンプレート化されたターゲットとして扱える。そのためターゲットには、呼ぶ API の名前ではなくパイプラインの ARN をそのまま書けばよい。[AWS 公式：テンプレート化されたターゲット](https://docs.aws.amazon.com/scheduler/latest/UserGuide/managing-targets-templated.html)

1. スケジューラ用の IAM ロールを作る。信頼ポリシーで `scheduler.amazonaws.com` を許可し、権限はこのパイプラインへの `codepipeline:StartPipelineExecution` だけにする。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "codepipeline:StartPipelineExecution",
      "Resource": "arn:aws:codepipeline:ap-northeast-1:111122223333:my-app"
    }
  ]
}
```

2. スケジュールを作る。毎日 日本時間 3:00 に実行する例。タイムゾーンを指定できるので、cron 式に日本時間のまま書ける。

```bash
aws scheduler create-schedule \
  --name my-app-nightly \
  --schedule-expression 'cron(0 3 * * ? *)' \
  --schedule-expression-timezone Asia/Tokyo \
  --flexible-time-window Mode=OFF \
  --target '{
    "Arn": "arn:aws:codepipeline:ap-northeast-1:111122223333:my-app",
    "RoleArn": "arn:aws:iam::111122223333:role/my-app-nightly-scheduler"
  }'
```

- push のトリガーと定期実行は両方とも有効になる。定期実行だけにするなら、ソースのアクションの設定に `"DetectChanges": "false"` を足し、push で動かないようにする。
- EventBridge の「ルール」でも同じことができ、CodePipeline のユーザーガイドはルールで説明している。[AWS 公式：スケジュールでパイプラインを開始する](https://docs.aws.amazon.com/codepipeline/latest/userguide/pipelines-trigger-source-schedule.html) ルールのスケジュールは UTC だけなので、ここではタイムゾーンを指定できる EventBridge Scheduler を使った。

## EC2 Image Builder

EC2 の AMI（およびコンテナイメージ）の作成・テスト・配布を自動化するサービス。OS のパッチ適用やミドルウェアの導入を済ませた「ゴールデンイメージ」を定期的に作り直すのに使う。

**主な概念**

- **イメージレシピ**: ベースイメージ（親イメージ）と、適用するコンポーネントの組み合わせ。
- **コンポーネント**: イメージに加える処理を YAML で書いたもの。ビルド用（ソフトウェアの導入・設定）とテスト用がある。AWS 提供のもの（CloudWatch エージェントの導入、CIS ベンチマークでの強化など）も使える。
- **インフラストラクチャ設定**: ビルドに使う一時インスタンスのタイプ、サブネット、セキュリティグループ、IAM ロール（インスタンスプロファイル）。
- **ディストリビューション設定**: できた AMI をどのリージョン・アカウントに配るか。起動テンプレートの AMI を自動で差し替えることもできる。
- **イメージパイプライン**: 上の設定をまとめ、スケジュールやベースイメージの更新をきっかけに実行する。
- **ライフサイクルポリシー**: 古いイメージを自動で廃止・削除する。

## 4 つの関係

| サービス | 自動化するもの | 入力 | 出力 |
| --- | --- | --- | --- |
| CodeBuild | ビルドとテスト | ソースコード、buildspec | 成果物、テスト結果 |
| CodeDeploy | アプリケーションの配置と切り替え | 成果物、appspec | 新しい版が動くサーバー・関数・コンテナ |
| CodePipeline | ビルドからデプロイまでの順序と実行のきっかけ | ソースの変更、EventBridge Scheduler からの定期実行 | デプロイされたアプリケーション |
| EC2 Image Builder | サーバーイメージの作成 | レシピ、コンポーネント | AMI、コンテナイメージ |
