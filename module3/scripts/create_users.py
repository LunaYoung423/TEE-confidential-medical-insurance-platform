"""初始化审计库中的 users / accounts 示例记录（需已存在 security_audit 库与表结构）。"""
from werkzeug.security import generate_password_hash
from sqlalchemy import select

from module3.audit.models import User, Account, get_session


def _ensure_user_account(session, username: str, password: str, account_name: str) -> None:
    existing = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if existing:
        print(f"已存在用户: {username} (user_id={existing.user_id})")
        acc = (
            session.execute(
                select(Account).where(
                    Account.user_id == existing.user_id,
                    Account.account_name == account_name,
                )
            )
            .scalar_one_or_none()
        )
        if not acc:
            session.add(Account(user_id=existing.user_id, account_name=account_name))
            session.commit()
            print(f"已为 {username} 补建账号: {account_name}")
        return

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
    )
    session.add(user)
    session.flush()
    session.add(Account(user_id=user.user_id, account_name=account_name))
    session.commit()
    print(f"用户创建成功: {username} user_id={user.user_id}, account={account_name}")


def main():
    session = get_session()
    try:
        _ensure_user_account(session, "admin", "admin123", "admin")
        _ensure_user_account(session, "user", "123456", "user")
    except Exception as e:
        session.rollback()
        print(f"创建失败: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
