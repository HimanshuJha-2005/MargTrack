permit(
    principal,
    action == Action::"DispatchRide",
    resource
)
when {
    resource.safety_score >= 70 &&
    resource.unresolved_violations == 0
};