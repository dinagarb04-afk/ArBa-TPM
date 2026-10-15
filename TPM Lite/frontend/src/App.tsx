import {
  Alert,
  Box,
  Button,
  Container,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Typography,
} from "@mui/material";
import { NavLink, Outlet, Route, Routes } from "react-router-dom";
import Dashboard from "./features/dashboard/Dashboard";
import {
  IntegrationMonitorPage,
  NewPromotionPage,
  PromotionReviewPage,
  PromotionWorklistPage,
} from "./features/promotions/PromotionPages";
import "./App.css";

function AppLayout() {
  return (
    <Box className="app-shell">
      <aside aria-label="Main navigation" className="app-sidebar">
        <NavLink aria-label="ArBa Trade Promotion Plan capability home" className="app-brand" to="/">
          <span aria-hidden="true" className="app-brand-mark">
            A
          </span>
          <span>
            <strong>ArBa Trade</strong>
            <small>Promotion Plan capability</small>
          </span>
        </NavLink>
        <Typography className="app-nav-label">WORKSPACE</Typography>
        <List className="app-navigation" disablePadding>
          <ListItemButton
            className="app-navigation-link"
            component={NavLink}
            end
            to="/"
          >
            <ListItemText primary="Promotion Overview" />
          </ListItemButton>
          <ListItemButton
            className="app-navigation-link"
            component={NavLink}
            to="/promotions"
          >
            <ListItemText primary="Promotion Worklist" />
          </ListItemButton>
          <ListItemButton
            className="app-navigation-link"
            component={NavLink}
            to="/integrations"
          >
            <ListItemText primary="Integration Monitor" />
          </ListItemButton>
        </List>
        <div className="app-sidebar-footer">
          <span className="app-demo-tag">SYNTHETIC DEVELOPMENT DATA</span>
          <span>Identity and role access are not configured.</span>
        </div>
      </aside>
      <main className="app-main">
        <Container className="app-content" maxWidth={false}>
          <Outlet />
        </Container>
      </main>
    </Box>
  );
}

function NotFoundPage() {
  return (
    <Paper className="app-placeholder-card" elevation={0}>
      <Typography component="h1" variant="h1">
        Page not found
      </Typography>
      <Button component={NavLink} to="/" variant="contained">
        Return to overview
      </Button>
    </Paper>
  );
}

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route element={<Dashboard />} index />
        <Route element={<PromotionWorklistPage />} path="promotions" />
        <Route element={<NewPromotionPage />} path="promotions/new" />
        <Route element={<PromotionReviewPage />} path="promotions/:promotionId" />
        <Route element={<IntegrationMonitorPage />} path="integrations" />
        <Route element={<NotFoundPage />} path="*" />
      </Route>
    </Routes>
  );
}

export default App;
