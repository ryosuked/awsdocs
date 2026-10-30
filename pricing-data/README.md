# 価格データ

[コスト見積もりの基礎情報](../cost-basics.md) の元にした、AWS の公開価格データ（Price List）。取得した日ごとにディレクトリを分けている。

## 2026-11-07/

東京リージョン（ap-northeast-1）の分。CloudFront だけはリージョンを持たないため全体の分。

| ファイル | 内容 | 取得元 |
| --- | --- | --- |
| `<サービスコード>.csv` | 各サービスの料金表（オンデマンド以外も含む） | `https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<サービスコード>/current/ap-northeast-1/index.csv` |
| `AmazonEC2-tokyo-linux-ondemand.json` | EC2 の Linux オンデマンド料金と、インスタンスの vCPU・メモリ | `https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/Asia%20Pacific%20(Tokyo)/Linux/index.json` |
| `AmazonEC2-ebs.json` | EBS の料金（全リージョン） | `https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ebs.json` |
| `AmazonEC2-natgateway.json` | NAT ゲートウェイの料金（全リージョン） | `https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/natgateway.json` |

EC2 全体の料金表（`AmazonEC2`）は東京リージョンだけで約 290 MB あるため取得していない。EC2・EBS・NAT ゲートウェイは、AWS の料金ページが使っている上の小さいデータで代えている。

## 検索

`query.py` で、CSV のオンデマンド料金を説明文や使用タイプの正規表現で探せる。

```sh
python3 query.py 2026-11-07/AWSQueueService.csv 'Requests'
python3 query.py 2026-11-07/AmazonS3.csv 'TimedStorage' 'Express|Outposts'   # 2 つ目は除外する条件
```
