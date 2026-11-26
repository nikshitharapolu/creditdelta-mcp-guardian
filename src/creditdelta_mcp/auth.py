import streamlit as st
from supabase import create_client


def get_user_client():
    # Each browser session gets its own authenticated client.
    if "supabase_client" not in st.session_state:
        st.session_state.supabase_client = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_PUBLISHABLE_KEY"],
        )
    return st.session_state.supabase_client


def _finish_sign_in(client):
    # Prevent another account from inheriting drafts or pending UI state.
    st.session_state.clear()
    st.session_state.supabase_client = client
    st.session_state.signed_in = True
    st.rerun()


def show_account():
    """Render account controls and return a verified user or None."""
    client = get_user_client()
    user = None

    if st.session_state.get("signed_in"):
        try:
            user = client.auth.get_user().user
        except Exception:
            user = None

        if user is None:
            st.session_state.clear()
            client = get_user_client()
            st.warning("Your login could not be verified. Please sign in again.")

    if user:
        st.caption(f"Signed in: {user.email}")

        if st.button("Sign out", key="account_sign_out"):
            try:
                client.auth.sign_out()
            except Exception:
                pass
            st.session_state.clear()
            st.rerun()

        return user

    with st.expander("Sign in / Create account"):
        st.caption("Analyze and download without an account. Sign in to save.")

        mode = st.radio(
            "Account",
            ["Sign in", "Create account"],
            key="account_mode",
            horizontal=True,
        )

        if mode == "Sign in":
            with st.form("account_login", clear_on_submit=True):
                email = st.text_input("Email", key="login_email")
                password = st.text_input(
                    "Password", type="password", key="login_password"
                )
                submitted = st.form_submit_button("Sign in")

            if submitted:
                if not email.strip() or not password:
                    st.warning("Enter your email and password.")
                else:
                    try:
                        response = client.auth.sign_in_with_password(
                            {"email": email.strip(), "password": password}
                        )
                        authenticated = bool(
                            response.session and client.auth.get_user().user
                        )
                    except Exception:
                        authenticated = False

                    if authenticated:
                        _finish_sign_in(client)
                    else:
                        # Discard any partially established login.
                        st.session_state.pop("supabase_client", None)
                        st.error(
                            "Sign-in failed. Check your email, password, "
                            "and email confirmation, then try again."
                        )

        else:
            with st.form("account_signup", clear_on_submit=True):
                email = st.text_input("Email", key="signup_email")
                password = st.text_input(
                    "Password", type="password", key="signup_password"
                )
                confirmation = st.text_input(
                    "Confirm password",
                    type="password",
                    key="signup_password_confirmation",
                )
                st.caption("Use at least 12 characters.")
                submitted = st.form_submit_button("Create account")

            if submitted:
                if not email.strip() or "@" not in email.strip():
                    st.warning("Enter a valid email address.")
                elif len(password) < 12:
                    st.warning("Use a password with at least 12 characters.")
                elif password != confirmation:
                    st.warning("Passwords do not match.")
                else:
                    try:
                        response = client.auth.sign_up(
                            {
                                "email": email.strip(),
                                "password": password,
                            }
                        )
                    except Exception:
                        st.error(
                            "Registration could not be completed. "
                            "Try again later, or sign in if you already "
                            "have an account."
                        )
                    else:
                        if response.session:
                            # Handles projects with confirmation disabled.
                            # Still verify the session before using it.
                            try:
                                verified = client.auth.get_user().user
                            except Exception:
                                verified = None

                            if verified:
                                _finish_sign_in(client)
                            else:
                                st.session_state.pop("supabase_client", None)
                                st.info("Please return to Sign in.")
                        else:
                            st.success(
                                "If this address is eligible for registration, "
                                "you'll receive a confirmation email. "
                                "Open its link, then return here and sign in."
                            )
                            st.caption(
                                "Already registered? Choose Sign in. "
                                "Also check your spam folder."
                            )

    return None