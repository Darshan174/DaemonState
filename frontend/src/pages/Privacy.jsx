import { Link } from "react-router-dom";

import DaemonStateIcon from "../components/DaemonStateIcon";
import "./LandingReplica.css";
import "./Privacy.css";


export default function Privacy() {
  return (
    <div className="dsr-landing dsr-privacy">
      <header className="dsr-privacy-header">
        <Link to="/" aria-label="DaemonState home" className="dsr-brand">
          <DaemonStateIcon size={29} />
          <span>DaemonState</span>
        </Link>
        <Link to="/#early-access" className="dsr-privacy-back">
          Return to early access
        </Link>
      </header>

      <main>
        <article>
          <p className="dsr-privacy-kicker">PUBLIC WAITLIST / PRIVACY</p>
          <h1>Privacy notice</h1>
          <p className="dsr-privacy-effective">Effective August 23, 2026</p>

          <p className="dsr-privacy-lead">
            This notice covers the DaemonState public website and early-access
            waitlist. DaemonState&apos;s self-hosted product stores project data in
            the environment chosen by its operator; that product data is not part
            of this public waitlist.
          </p>

          <section>
            <h2>Information collected</h2>
            <p>
              When you join, Clerk stores your email address and waitlist status
              so an approved signup can become an account. The site may separately
              record campaign parameters attached to the page URL and the referring
              site and path; query strings and fragments are removed from referrer
              URLs before they are recorded.
            </p>
            <p>
              Deployments without Clerk use the same-origin waitlist fallback,
              which also stores the time and version of the consent notice. The
              hosted fallback uses Cloudflare D1; self-hosted operators use their
              configured database. A waitlist record can contain operational fields
              such as invitation status, contact history, and internal notes.
            </p>
          </section>

          <section>
            <h2>How the information is used</h2>
            <p>
              We use waitlist information to manage private-beta access, send
              requested product updates, understand which launch channels work,
              select useful design partners, and improve onboarding. We do not
              sell waitlist information.
            </p>
          </section>

          <section>
            <h2>Service providers</h2>
            <p>
              Cloudflare hosts the public site. Clerk manages the hosted waitlist,
              confirmation emails, approvals, and approved-user account signup.
              The hosted fallback stores entries in Cloudflare D1 and may use Loops
              for waitlist email. PostHog receives a small set of manually defined
              website events; it does not receive your email address, and session
              replay and autocapture are disabled.
            </p>
          </section>

          <section>
            <h2>Retention and your choices</h2>
            <p>
              We keep a waitlist record while early access is operating or while
              it is reasonably needed for beta communication. You can unsubscribe
              using the link in an email. You can also ask for access, correction,
              or deletion by contacting the repository owner privately through
              the contact method on the owner&apos;s GitHub profile. Do not put your
              email address or other personal information in a public issue.
            </p>
            <a
              href="https://github.com/Darshan174"
              target="_blank"
              rel="noreferrer"
              className="dsr-privacy-contact"
            >
              Contact the repository owner
            </a>
          </section>

          <section>
            <h2>Changes to this notice</h2>
            <p>
              Material changes will be reflected on this page with a new effective
              date. The consent version stored with new signups is updated when the
              waitlist notice changes.
            </p>
          </section>
        </article>
      </main>

      <footer className="dsr-privacy-footer">
        <span>© 2026 DaemonState</span>
        <nav aria-label="Legal navigation">
          <Link to="/permissions-terms">Permissions &amp; terms</Link>
          <Link to="/">daemonstate.com</Link>
        </nav>
      </footer>
    </div>
  );
}
