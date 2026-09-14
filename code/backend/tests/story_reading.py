"""Advance only readable story passages, preserving every business gate."""
from serious_game_backend.application.package_lock import require_locked_package


def read_available_story(client, session_id, headers, prefix):
    for _ in range(100):
        response = client.get(f"/api/game/session/{session_id}/view", headers=headers)
        assert response.status_code == 200, response.text
        view = response.json()
        if not view['commands'].get('can_continue_story'):
            return {'visible_state': view['state'], 'state_version': view['state']['state_version']}
        response = client.post(
            f"/api/game/session/{session_id}/story/continue", headers=headers,
            json={'client_action_id': f"{prefix}-read-{view['state']['state_version']}",
                  'state_version': view['state']['state_version']},
        )
        assert response.status_code == 200, response.text
    raise AssertionError('Story reading did not terminate within 100 passages')


def read_service_story(end_days, sessions, packages, account_id, session_id, prefix):
    for _ in range(100):
        session = sessions.get_owned(session_id, account_id)
        package = require_locked_package(packages, session)
        if not end_days._story_flow.unread_day_continuation(session, package):
            return session
        end_days.end_day(account_id=account_id, session_id=session_id,
                        client_action_id=f'{prefix}-read-{session.state_version}',
                        state_version=session.state_version, continue_story_only=True)
    raise AssertionError('Story reading did not terminate within 100 passages')
