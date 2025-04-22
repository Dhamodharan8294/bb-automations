import os

os.environ['EVENTS_IGNORED_WHEN_QUEUE_MISSING'] = '''
{
    "test-source-1": ["test-detail-type-1", "test-detail-type-2"],
    "test-source-2": ["test-detail-type-1", "test-detail-type-2"]
}
'''
