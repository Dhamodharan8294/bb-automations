from enum import Enum, auto, unique


@unique
class DetailFormat(Enum):
    DETAIL_ONLY = auto()
    OLD_IMAGE_ONLY = auto()
    NEW_IMAGE_ONLY = auto()
    OLD_AND_NEW_IMAGE_ONLY = auto()
    OLD_AND_NEW_IMAGE_WITH_DETAIL = auto()


def mock_event_bridge_event(tenant_id: str = 'mock-tenant-id',
                            source: str = 'bb.enterprise.data.source',
                            detail_type: str = 'Create',
                            detail_format: DetailFormat = DetailFormat.DETAIL_ONLY) -> dict:
    return {
        "source": source,
        "detail-type": detail_type,
        "detail": get_detail(tenant_id, detail_format),
        "version": "0",
        "id": "892e33f6-1005-e394-69b8-52dc1593bd9a",
        "account": "257597320193",
        "time": "2020-06-19T00:45:05Z",
        "region": 'us-east-1',
        "resources": [],
    }


def get_detail(tenant_id: str, detail_format: DetailFormat) -> dict:
    if detail_format == DetailFormat.DETAIL_ONLY:
        return mock_data_source_event(tenant_id=tenant_id)
    if detail_format == DetailFormat.OLD_IMAGE_ONLY:
        return {
            'OldImage': mock_data_source_event(tenant_id=f'{tenant_id}-in-old-image')
        }
    if detail_format == DetailFormat.NEW_IMAGE_ONLY:
        return {
            'NewImage': mock_data_source_event(tenant_id=f'{tenant_id}-in-new-image')
        }
    if detail_format == DetailFormat.OLD_AND_NEW_IMAGE_ONLY:
        return {
            'OldImage': mock_data_source_event(tenant_id=f'{tenant_id}-in-old-image'),
            'NewImage': mock_data_source_event(tenant_id=f'{tenant_id}-in-new-image')
        }
    if detail_format == DetailFormat.OLD_AND_NEW_IMAGE_WITH_DETAIL:
        return {
            **mock_data_source_event(tenant_id=f'{tenant_id}-in-detail'), 'OldImage': mock_data_source_event(
                tenant_id=f'{tenant_id}-in-old-image'),
            'NewImage': mock_data_source_event(tenant_id=f'{tenant_id}-in-new-image')
        }
    raise Exception(f'Unsupported detail-format {detail_format}')


def mock_data_source_event(tenant_id: str):
    return {
        "id": "23253265-c53c-45c0-94c4-8df6a9d46c8b",
        "tenantId": tenant_id,
        "created": "2019-07-15T23:28:33.359Z",
        "modified": "2020-05-08T00:26:34.123Z",
        "version": 23,
        "description": "Spring 2020 term",
        "owner": "Learn",
        "ids": {
            "pk1": "_123_1",
            "externalId": "Spring2020"
        }
    }
